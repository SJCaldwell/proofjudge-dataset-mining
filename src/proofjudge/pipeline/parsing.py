"""Phase 4: Proof block extraction and pair matching.

For each extracted PR, fetches .lean file content at the first and last
commit SHAs, parses both versions into proof blocks, matches declarations
by name, and keeps only pairs where the proof body changed.
"""

import asyncio
import logging
import re
from collections import Counter
from pathlib import Path

from proofjudge.config import Settings
from proofjudge.github.client import GitHubClient
from proofjudge.github.rest import fetch_file_content
from proofjudge.lean.parser import extract_proof_blocks
from proofjudge.models.comments import PRExtraction
from proofjudge.models.pr import INFRA_PATH_PREFIXES
from proofjudge.models.proof import ProofBlock, ProofPair, PRParsingResult
from proofjudge.storage.database import Database
from proofjudge.storage.jsonl import read_json_file, write_json_file

logger = logging.getLogger(__name__)

# Minimum number of net changed tokens (added + removed) to keep a pair.
# Filters out trivial parenthesization, whitespace normalization, etc.
_MIN_CHANGED_TOKENS = 3

# Minimum proportion of tokens that must change relative to the shorter proof.
# Catches cases like a 116-line proof where only 1 tactic name changes.
_MIN_CHANGE_PROPORTION = 0.05

# Tokenize Lean source into identifiers and single-char operators
_TOKEN_RE = re.compile(r"[a-zA-Z_][\w'.]*|[^\s]")


def _tokenize(text: str) -> list[str]:
    """Tokenize Lean source into words and operator tokens."""
    return _TOKEN_RE.findall(text)


def _is_only_refine_migration(initial_body: str, final_body: str) -> bool:
    """Detect the mechanical refine' -> refine migration.

    Returns True if the only differences between the two bodies are:
    - ``refine'`` replaced by ``refine``
    - ``_`` replaced by ``?_`` (the placeholder syntax change)
    """
    normalized_initial = initial_body.replace("refine'", "refine").replace(" _", " ?_")
    normalized_final = final_body.replace("refine'", "refine").replace(" _", " ?_")
    return normalized_initial.strip() == normalized_final.strip()


def _is_meaningful_change(initial_body: str, final_body: str) -> bool:
    """Check if the difference between two proof bodies is meaningful.

    Uses bag-of-tokens comparison (position-independent) to count the
    net added + removed tokens. This avoids false positives from trivial
    changes like adding/removing a single parenthesis.
    """
    # Filter mechanical refine' -> refine migration
    if _is_only_refine_migration(initial_body, final_body):
        return False

    initial_tokens = _tokenize(initial_body)
    final_tokens = _tokenize(final_body)

    if initial_tokens == final_tokens:
        return False

    # Bag-of-tokens diff: count tokens present in one but not the other
    initial_counts = Counter(initial_tokens)
    final_counts = Counter(final_tokens)
    added = sum((final_counts - initial_counts).values())
    removed = sum((initial_counts - final_counts).values())
    changed = added + removed

    if changed < _MIN_CHANGED_TOKENS:
        return False

    # Proportional filter: avoid keeping large proofs with tiny changes
    shorter_len = min(len(initial_tokens), len(final_tokens))
    return not (shorter_len > 0 and changed / shorter_len < _MIN_CHANGE_PROPORTION)


def _match_proof_pairs(
    pr_number: int,
    file_path: str,
    initial_blocks: list[ProofBlock],
    final_blocks: list[ProofBlock],
) -> list[ProofPair]:
    """Match proof blocks by declaration name and find changed pairs."""
    # Index by name (skip unnamed declarations like examples)
    initial_by_name: dict[str, ProofBlock] = {}
    for block in initial_blocks:
        if block.name:
            initial_by_name[block.name] = block

    final_by_name: dict[str, ProofBlock] = {}
    for block in final_blocks:
        if block.name:
            final_by_name[block.name] = block

    pairs: list[ProofPair] = []
    for name, initial in initial_by_name.items():
        final = final_by_name.get(name)
        if final is None:
            continue

        # Skip if bodies are identical after stripping whitespace
        if initial.body.strip() == final.body.strip():
            continue

        # Skip trivially small changes
        if not _is_meaningful_change(initial.body, final.body):
            logger.debug(
                "PR #%d: skipping trivial change to %s",
                pr_number,
                name,
            )
            continue

        pairs.append(
            ProofPair(
                pr_number=pr_number,
                file_path=file_path,
                declaration_name=name,
                declaration_kind=final.kind,
                initial_proof=initial,
                final_proof=final,
            )
        )

    return pairs


async def parse_single_pr(
    client: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    extraction_dir: Path,
) -> list[ProofPair]:
    """Parse proof pairs from an extracted PR.

    Fetches file content at first/last commit SHAs, parses both versions,
    matches declarations by name, and returns pairs where the proof changed.
    """
    extraction_path = extraction_dir / f"pr_{pr_number}.json"
    extraction = read_json_file(extraction_path, PRExtraction)

    if extraction is None:
        logger.warning("No extraction data for PR #%d", pr_number)
        return []

    if extraction.first_commit_sha == extraction.last_commit_sha:
        logger.debug(
            "PR #%d has single commit, skipping parsing", pr_number
        )
        return []

    all_pairs: list[ProofPair] = []

    # Process each .lean file changed in the PR.
    #
    # The infra filter must be applied HERE, not only in `is_proof_touching`.
    # That property is a PR-level any() check — "does this PR touch at least one
    # non-infra .lean file" — so a PR touching both Mathlib/Algebra/Foo.lean and
    # scripts/lint-style.lean qualifies on the former and, without this filter,
    # contributes declarations from BOTH. That leak put 97 non-mathematical rows
    # (linters, CLI tools, tactic implementations) into a 4,196-row dataset.
    lean_files = [
        f
        for f in extraction.files_changed
        if f.path.endswith(".lean")
        and not any(f.path.startswith(prefix) for prefix in INFRA_PATH_PREFIXES)
    ]

    for file_info in lean_files:
        try:
            # Fetch both versions concurrently
            initial_content, final_content = await asyncio.gather(
                fetch_file_content(
                    client,
                    owner,
                    repo,
                    file_info.path,
                    extraction.first_commit_sha,
                ),
                fetch_file_content(
                    client,
                    owner,
                    repo,
                    file_info.path,
                    extraction.last_commit_sha,
                ),
            )

            if initial_content is None and final_content is None:
                continue

            initial_blocks = (
                extract_proof_blocks(initial_content, file_info.path)
                if initial_content
                else []
            )
            final_blocks = (
                extract_proof_blocks(final_content, file_info.path)
                if final_content
                else []
            )

            pairs = _match_proof_pairs(
                pr_number, file_info.path, initial_blocks, final_blocks
            )
            all_pairs.extend(pairs)

            if pairs:
                logger.info(
                    "PR #%d %s: found %d changed proof(s)",
                    pr_number,
                    file_info.path,
                    len(pairs),
                )
        except Exception:
            logger.warning(
                "PR #%d: failed to parse %s",
                pr_number,
                file_info.path,
                exc_info=True,
            )

    return all_pairs


async def run_parsing(
    client: GitHubClient,
    db: Database,
    settings: Settings,
    limit: int | None = None,
    concurrency: int = 3,
) -> int:
    """Run proof parsing for all extracted PRs.

    Returns the number of PRs successfully parsed.
    """
    pending = db.get_prs_needing_parsing(limit=limit)

    if not pending:
        logger.info("No PRs need parsing")
        return 0

    logger.info("Parsing %d PRs...", len(pending))
    semaphore = asyncio.Semaphore(concurrency)
    parsed_count = 0

    async def parse_with_semaphore(pr_number: int) -> bool:
        async with semaphore:
            try:
                pairs = await parse_single_pr(
                    client,
                    settings.github_owner,
                    settings.github_repo,
                    pr_number,
                    settings.extraction_dir,
                )

                # Write results
                result = PRParsingResult(
                    pr_number=pr_number,
                    pairs=pairs,
                    pair_count=len(pairs),
                )
                output_path = settings.parsing_dir / f"pr_{pr_number}.json"
                write_json_file(output_path, result)

                db.mark_phase_complete(pr_number, "parsed_at")

                logger.info(
                    "Parsed PR #%d: %d proof pair(s) found",
                    pr_number,
                    len(pairs),
                )
                return True
            except Exception:
                db.record_error(pr_number, "parsing failed")
                logger.error(
                    "Failed to parse PR #%d",
                    pr_number,
                    exc_info=True,
                )
                return False

    tasks = [parse_with_semaphore(pr) for pr in pending]
    results = await asyncio.gather(*tasks)
    parsed_count = sum(1 for r in results if r)

    logger.info(
        "Parsing complete: %d/%d PRs succeeded", parsed_count, len(pending)
    )
    return parsed_count
