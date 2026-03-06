"""Phase 5: LLM-based classification and summarization of proof pairs.

For each parsed PR, sends proof pairs to Claude for quality classification
(HIGH_VALUE / LOW_VALUE / CONTEXTUAL) and generates structured summaries
of what changed and why.
"""

import logging
from typing import Any

from proofjudge.config import Settings
from proofjudge.models.comments import PRExtraction
from proofjudge.models.pr import BORS_TITLE_PREFIX, PRMetadata
from proofjudge.models.proof import ProofPair, PRParsingResult
from proofjudge.models.triplet import (
    FeedbackCategory,
    PairSummarization,
    PRSummarizationResult,
    QualityVerdict,
)
from proofjudge.pipeline.llm import LLMClient
from proofjudge.pipeline.prompts import SYSTEM_PROMPT, build_user_prompt
from proofjudge.storage.database import Database
from proofjudge.storage.jsonl import read_json_file, read_jsonl, write_json_file

logger = logging.getLogger(__name__)


def _parse_categories(raw: list[object]) -> list[FeedbackCategory]:
    """Parse category strings into FeedbackCategory enum values."""
    result: list[FeedbackCategory] = []
    for item in raw:
        s = str(item)
        try:
            result.append(FeedbackCategory(s))
        except ValueError:
            logger.warning("Unknown feedback category: %s", s)
            result.append(FeedbackCategory.OTHER)
    return result


def _parse_verdict(raw: str) -> QualityVerdict:
    """Parse verdict string, with fallback."""
    try:
        return QualityVerdict(raw)
    except ValueError:
        logger.warning("Unknown verdict: %s, defaulting to LOW_VALUE", raw)
        return QualityVerdict.LOW_VALUE


def _parse_llm_response(
    response: dict[str, Any],
    pair: ProofPair,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> PairSummarization:
    """Convert raw LLM JSON response into a typed PairSummarization."""
    return PairSummarization(
        declaration_name=pair.declaration_name,
        file_path=pair.file_path,
        verdict=_parse_verdict(str(response.get("verdict", "LOW_VALUE"))),
        verdict_reasoning=str(response.get("verdict_reasoning", "")),
        summary=str(response.get("summary", "")),
        categories=_parse_categories(response.get("categories", [])),
        key_changes=[str(c) for c in response.get("key_changes", [])],
        reviewer_quotes=[str(q) for q in response.get("reviewer_quotes", [])],
        has_explicit_review_feedback=bool(response.get("has_explicit_review_feedback", False)),
        confidence=float(response.get("confidence", 0.5)),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


async def summarize_single_pair(
    llm: LLMClient,
    pair: ProofPair,
    extraction: PRExtraction,
    pr_title: str,
) -> PairSummarization:
    """Classify and summarize a single proof pair via the LLM."""
    user_prompt = build_user_prompt(pair, extraction, pr_title)
    response, input_tokens, output_tokens = await llm.classify_pair(SYSTEM_PROMPT, user_prompt)
    return _parse_llm_response(response, pair, llm.model, input_tokens, output_tokens)


async def summarize_pr(
    llm: LLMClient,
    pr_number: int,
    settings: Settings,
    pr_title: str,
) -> PRSummarizationResult | None:
    """Summarize all proof pairs for a single PR.

    Reads parsing and extraction data from disk, processes pairs sequentially,
    and returns the aggregated result.
    """
    parsing_path = settings.parsing_dir / f"pr_{pr_number}.json"
    parsing_result = read_json_file(parsing_path, PRParsingResult)
    if parsing_result is None:
        logger.warning("No parsing data for PR #%d", pr_number)
        return None

    if not parsing_result.pairs:
        logger.debug("PR #%d has no proof pairs, skipping", pr_number)
        return PRSummarizationResult(
            pr_number=pr_number,
            pair_results=[],
            high_value_count=0,
            low_value_count=0,
            contextual_count=0,
            total_input_tokens=0,
            total_output_tokens=0,
        )

    extraction_path = settings.extraction_dir / f"pr_{pr_number}.json"
    extraction = read_json_file(extraction_path, PRExtraction)
    if extraction is None:
        logger.warning("No extraction data for PR #%d", pr_number)
        return None

    pair_results: list[PairSummarization] = []
    total_input = 0
    total_output = 0

    for pair in parsing_result.pairs:
        try:
            result = await summarize_single_pair(llm, pair, extraction, pr_title)
            pair_results.append(result)
            total_input += result.input_tokens
            total_output += result.output_tokens
            logger.info(
                "PR #%d %s: %s (confidence=%.2f)",
                pr_number,
                pair.declaration_name or "(unnamed)",
                result.verdict.value,
                result.confidence,
            )
        except Exception:
            logger.error(
                "PR #%d: failed to summarize pair %s",
                pr_number,
                pair.declaration_name,
                exc_info=True,
            )

    verdict_counts = dict.fromkeys(QualityVerdict, 0)
    for r in pair_results:
        verdict_counts[r.verdict] += 1

    return PRSummarizationResult(
        pr_number=pr_number,
        pair_results=pair_results,
        high_value_count=verdict_counts[QualityVerdict.HIGH_VALUE],
        low_value_count=verdict_counts[QualityVerdict.LOW_VALUE],
        contextual_count=verdict_counts[QualityVerdict.CONTEXTUAL],
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )


def _load_pr_titles(settings: Settings) -> dict[int, str]:
    """Load PR titles from the enrichment JSONL for use in prompts."""
    titles: dict[int, str] = {}
    metadata_path = settings.enrichment_dir / "pr_metadata.jsonl"
    for pr in read_jsonl(metadata_path, PRMetadata):
        title = pr.title
        if title.startswith(BORS_TITLE_PREFIX):
            title = title[len(BORS_TITLE_PREFIX):]
        titles[pr.number] = title
    return titles


async def run_summarization(
    llm: LLMClient,
    db: Database,
    settings: Settings,
    limit: int | None = None,
) -> int:
    """Run summarization for all parsed PRs.

    Returns the number of PRs successfully summarized.
    """
    pending = db.get_prs_needing_summarization(limit=limit)

    if not pending:
        logger.info("No PRs need summarization")
        return 0

    logger.info("Summarizing %d PRs...", len(pending))

    # Pre-load PR titles
    titles = _load_pr_titles(settings)

    settings.summarization_dir.mkdir(parents=True, exist_ok=True)
    summarized_count = 0
    total_high = 0
    total_low = 0
    total_contextual = 0

    for pr_number in pending:
        pr_title = titles.get(pr_number, f"PR #{pr_number}")
        try:
            result = await summarize_pr(llm, pr_number, settings, pr_title)
            if result is None:
                db.record_error(pr_number, "summarization: no parsing/extraction data")
                continue

            # Write result
            output_path = settings.summarization_dir / f"pr_{pr_number}.json"
            write_json_file(output_path, result)

            db.mark_phase_complete(pr_number, "summarized_at")
            summarized_count += 1
            total_high += result.high_value_count
            total_low += result.low_value_count
            total_contextual += result.contextual_count

            logger.info(
                "Summarized PR #%d: %d HIGH, %d LOW, %d CONTEXTUAL (%d+%d tokens)",
                pr_number,
                result.high_value_count,
                result.low_value_count,
                result.contextual_count,
                result.total_input_tokens,
                result.total_output_tokens,
            )
        except Exception:
            db.record_error(pr_number, "summarization failed")
            logger.error("Failed to summarize PR #%d", pr_number, exc_info=True)

    logger.info(
        "Summarization complete: %d/%d PRs, %d HIGH, %d LOW, %d CONTEXTUAL",
        summarized_count,
        len(pending),
        total_high,
        total_low,
        total_contextual,
    )
    return summarized_count
