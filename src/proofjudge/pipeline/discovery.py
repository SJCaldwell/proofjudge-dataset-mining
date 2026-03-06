"""Phase 1: Discover candidate PR numbers via GraphQL scan and keyword search."""

import logging

from proofjudge.config import Settings
from proofjudge.github.client import GitHubClient
from proofjudge.github.graphql import fetch_pr_metadata_batch
from proofjudge.github.search import run_keyword_searches
from proofjudge.models.pr import PRMetadata
from proofjudge.storage.database import Database
from proofjudge.storage.jsonl import append_jsonl

logger = logging.getLogger(__name__)


async def run_graphql_scan(
    client: GitHubClient,
    db: Database,
    settings: Settings,
    limit: int | None = None,
) -> int:
    """Scan all closed PRs via GraphQL pagination.

    Stores PR metadata and tracks progress via scan cursors.
    Returns the number of PRs processed.
    """
    scan_id = "closed_prs_desc"
    cursor = db.get_scan_cursor(scan_id)
    total_fetched = 0

    if cursor:
        logger.info("Resuming GraphQL scan from cursor %s...", cursor[:20])

    while True:
        prs, next_cursor, has_next, total_count = await fetch_pr_metadata_batch(
            client,
            settings.github_owner,
            settings.github_repo,
            cursor=cursor,
        )

        if not prs:
            break

        for pr in prs:
            _store_pr(db, pr, settings)
            total_fetched += 1

        db.update_scan_cursor(scan_id, next_cursor, total_fetched, total_count)
        logger.info(
            "GraphQL scan: fetched %d/%d PRs",
            total_fetched,
            total_count,
        )

        if not has_next or next_cursor is None:
            break

        cursor = next_cursor

        if limit and total_fetched >= limit:
            logger.info("Hit scan limit at %d PRs", total_fetched)
            break

    return total_fetched


def _store_pr(db: Database, pr: PRMetadata, settings: Settings) -> None:
    """Store a PR's discovery record and enrichment metadata."""
    db.upsert_candidate(pr.number, "full_scan")

    # Since we get full metadata from GraphQL, we can do enrichment inline
    db.mark_enriched(
        pr_number=pr.number,
        bors_status=pr.bors_status.value,
        has_lean_files=pr.has_lean_files,
        review_count=pr.review_count,
        review_thread_count=pr.review_thread_count,
        comment_count=pr.comment_count,
        qualifies=pr.qualifies_for_extraction,
    )

    # Also persist full metadata to JSONL
    append_jsonl(settings.enrichment_dir / "pr_metadata.jsonl", pr)


async def run_discovery(
    client: GitHubClient,
    db: Database,
    settings: Settings,
    *,
    full_scan: bool = True,
    keywords: bool = True,
    scan_limit: int | None = None,
) -> None:
    """Run the full discovery phase."""
    if full_scan:
        logger.info("Starting GraphQL full scan...")
        count = await run_graphql_scan(client, db, settings, limit=scan_limit)
        logger.info("GraphQL scan complete: %d PRs processed", count)

    if keywords:
        logger.info("Starting keyword searches...")
        count = await run_keyword_searches(client, db)
        logger.info("Keyword searches complete: %d PRs found", count)

    counts = db.get_phase_counts()
    logger.info(
        "Discovery complete: %d discovered, %d enriched, %d qualified",
        counts["discovered"],
        counts["enriched"],
        counts["qualified"],
    )
