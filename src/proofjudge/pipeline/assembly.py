"""Phase 6: Assemble proof triplets into HuggingFace dataset format.

Reads summarization results, filters to HIGH_VALUE pairs, joins with
PR metadata and proof content, and exports a flat JSONL file loadable
via datasets.load_dataset("json", ...).
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from proofjudge.config import Settings
from proofjudge.models.comments import PRExtraction
from proofjudge.models.context import PRContext
from proofjudge.models.pr import BORS_TITLE_PREFIX, PRMetadata
from proofjudge.models.proof import ProofPair, PRParsingResult
from proofjudge.models.triplet import (
    HuggingFaceRow,
    PairSummarization,
    PRSummarizationResult,
    QualityVerdict,
)
from proofjudge.storage.database import Database
from proofjudge.storage.jsonl import append_jsonl, read_json_file, read_jsonl

logger = logging.getLogger(__name__)

MATHLIB_PR_URL = "https://github.com/leanprover-community/mathlib4/pull"


def _find_pair_for_summarization(
    pairs: list[ProofPair],
    summarization: PairSummarization,
) -> ProofPair | None:
    """Find the ProofPair matching a PairSummarization by declaration name and file."""
    for pair in pairs:
        name_match = pair.declaration_name == summarization.declaration_name
        if name_match and pair.file_path == summarization.file_path:
            return pair
    return None


def triplet_to_hf_row(
    pair: ProofPair,
    summarization: PairSummarization,
    metadata: PRMetadata,
    dataset_version: str,
    *,
    base_commit_sha: str = "",
    first_commit_sha: str = "",
    last_commit_sha: str = "",
) -> HuggingFaceRow:
    """Convert a proof pair + summarization into a flat HuggingFace row."""
    title = metadata.title
    if title.startswith(BORS_TITLE_PREFIX):
        title = title[len(BORS_TITLE_PREFIX):]

    closed_at_str = metadata.closed_at.isoformat() if metadata.closed_at else ""
    created_at_str = metadata.created_at.isoformat()

    if metadata.closed_at:
        duration = (metadata.closed_at - metadata.created_at).total_seconds() / 86400.0
    else:
        duration = 0.0

    return HuggingFaceRow(
        initial_proof=pair.initial_proof.full_text,
        final_proof=pair.final_proof.full_text,
        rejection_reasons=summarization.summary,
        pr_number=metadata.number,
        pr_url=f"{MATHLIB_PR_URL}/{metadata.number}",
        file_path=pair.file_path,
        declaration_name=pair.declaration_name or "(unnamed)",
        declaration_kind=pair.declaration_kind.value,
        feedback_categories=[c.value for c in summarization.categories],
        key_changes=summarization.key_changes,
        pr_title=title,
        pr_author=metadata.author,
        reviewers=[],  # filled in below if extraction available
        created_at=created_at_str,
        closed_at=closed_at_str,
        review_duration_days=round(duration, 2),
        initial_line_count=pair.initial_line_count,
        final_line_count=pair.final_line_count,
        line_count_delta=pair.line_count_delta,
        signature_changed=pair.signature_changed,
        base_commit_sha=base_commit_sha,
        first_commit_sha=first_commit_sha,
        last_commit_sha=last_commit_sha,
        dataset_version=dataset_version,
        extraction_date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )


def assemble_pr(
    pr_number: int,
    settings: Settings,
    metadata: PRMetadata,
    dataset_version: str,
) -> list[HuggingFaceRow]:
    """Assemble HuggingFace rows for a single PR.

    Only includes HIGH_VALUE pairs.
    """
    # Load summarization result
    summ_path = settings.summarization_dir / f"pr_{pr_number}.json"
    summ_result = read_json_file(summ_path, PRSummarizationResult)
    if summ_result is None:
        logger.warning("No summarization data for PR #%d", pr_number)
        return []

    # Load parsing result for proof content
    parsing_path = settings.parsing_dir / f"pr_{pr_number}.json"
    parsing_result = read_json_file(parsing_path, PRParsingResult)
    if parsing_result is None:
        logger.warning("No parsing data for PR #%d", pr_number)
        return []

    # Load extraction for reviewer info + SHAs
    extraction_path = settings.extraction_dir / f"pr_{pr_number}.json"
    extraction = read_json_file(extraction_path, PRExtraction)
    reviewers = extraction.reviewer_usernames if extraction else []
    first_sha = extraction.first_commit_sha if extraction else ""
    last_sha = extraction.last_commit_sha if extraction else ""

    # Load context for base commit SHA (if available)
    context_path = settings.contexts_dir / f"pr_{pr_number}.json"
    context = read_json_file(context_path, PRContext)
    base_sha = context.base_commit_sha if context else ""

    rows: list[HuggingFaceRow] = []
    for pair_summ in summ_result.pair_results:
        if pair_summ.verdict != QualityVerdict.HIGH_VALUE:
            continue

        pair = _find_pair_for_summarization(parsing_result.pairs, pair_summ)
        if pair is None:
            logger.warning(
                "PR #%d: no matching pair for summarization of %s",
                pr_number,
                pair_summ.declaration_name,
            )
            continue

        row = triplet_to_hf_row(
            pair,
            pair_summ,
            metadata,
            dataset_version,
            base_commit_sha=base_sha,
            first_commit_sha=first_sha,
            last_commit_sha=last_sha,
        )
        # Fill in reviewers from extraction
        row = row.model_copy(update={"reviewers": reviewers})
        rows.append(row)

    return rows


def run_assembly(
    db: Database,
    settings: Settings,
    limit: int | None = None,
    dataset_version: str = "v0.1",
) -> int:
    """Run assembly for all summarized PRs.

    Returns the number of PRs successfully assembled.
    """
    pending = db.get_prs_needing_assembly(limit=limit)

    if not pending:
        logger.info("No PRs need assembly")
        return 0

    logger.info("Assembling %d PRs...", len(pending))

    # Pre-load metadata
    metadata_by_number: dict[int, PRMetadata] = {}
    metadata_path = settings.enrichment_dir / "pr_metadata.jsonl"
    for pr in read_jsonl(metadata_path, PRMetadata):
        metadata_by_number[pr.number] = pr

    output_path = settings.dataset_dir / "proofjudge.jsonl"
    settings.dataset_dir.mkdir(parents=True, exist_ok=True)

    # Track existing rows for deduplication
    seen_keys: set[tuple[int, str]] = set()

    # Load existing rows to avoid duplicates
    if output_path.exists():
        for row in read_jsonl(output_path, HuggingFaceRow):
            seen_keys.add((row.pr_number, row.declaration_name))

    assembled_count = 0
    total_rows = 0

    for pr_number in pending:
        metadata = metadata_by_number.get(pr_number)
        if metadata is None:
            logger.warning("No metadata for PR #%d, skipping assembly", pr_number)
            db.record_error(pr_number, "assembly: no metadata")
            continue

        try:
            rows = assemble_pr(pr_number, settings, metadata, dataset_version)

            new_rows = 0
            for row in rows:
                key = (row.pr_number, row.declaration_name)
                if key in seen_keys:
                    logger.debug(
                        "Skipping duplicate: PR #%d %s",
                        row.pr_number, row.declaration_name,
                    )
                    continue
                append_jsonl(output_path, row)
                seen_keys.add(key)
                new_rows += 1

            db.mark_phase_complete(pr_number, "assembled_at")
            assembled_count += 1
            total_rows += new_rows

            if new_rows > 0:
                logger.info(
                    "Assembled PR #%d: %d new row(s)",
                    pr_number,
                    new_rows,
                )
        except Exception:
            db.record_error(pr_number, "assembly failed")
            logger.error("Failed to assemble PR #%d", pr_number, exc_info=True)

    # Write dataset info
    _write_dataset_info(settings.dataset_dir, len(seen_keys), dataset_version)

    logger.info(
        "Assembly complete: %d/%d PRs, %d new rows",
        assembled_count,
        len(pending),
        total_rows,
    )
    return assembled_count


def _write_dataset_info(dataset_dir: Path, total_rows: int, version: str) -> None:
    """Write a dataset_info.json file for HuggingFace compatibility."""
    info = {
        "dataset_name": "proofjudge",
        "version": version,
        "description": (
            "Proof quality improvement triplets mined from mathlib4 PRs. "
            "Each row contains an initial proof, a final (improved) proof, "
            "and a summary of why the proof was changed."
        ),
        "total_rows": total_rows,
        "source": "leanprover-community/mathlib4",
        "generated_at": datetime.now(UTC).isoformat(),
    }
    info_path = dataset_dir / "dataset_info.json"
    info_path.write_text(json.dumps(info, indent=2) + "\n")
