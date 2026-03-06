"""Phase 2: Enrich PR candidates with metadata via GraphQL batch queries.

Note: When PRs are discovered via the full GraphQL scan (Phase 1), enrichment
happens inline since the scan already returns full metadata. This phase is
needed for PRs discovered via keyword search, which only yields PR numbers.
"""

import logging

from proofjudge.config import Settings
from proofjudge.github.client import GitHubClient
from proofjudge.github.graphql import fetch_prs_by_numbers
from proofjudge.storage.database import Database
from proofjudge.storage.jsonl import append_jsonl

logger = logging.getLogger(__name__)


async def run_enrichment(
    client: GitHubClient,
    db: Database,
    settings: Settings,
    limit: int | None = None,
) -> int:
    """Enrich PRs that were discovered but not yet enriched.

    This handles PRs found via keyword search that weren't part of the
    full GraphQL scan.

    Returns the number of PRs enriched.
    """
    pending = db.get_prs_needing_enrichment(limit=limit)
    if not pending:
        logger.info("No PRs need enrichment")
        return 0

    logger.info("Enriching %d PRs...", len(pending))
    enriched = 0

    # Fetch in batches of 20 (GraphQL alias limit)
    batch_size = 20
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        prs = await fetch_prs_by_numbers(client, settings.github_owner, settings.github_repo, batch)

        for pr in prs:
            db.mark_enriched(
                pr_number=pr.number,
                bors_status=pr.bors_status.value,
                has_lean_files=pr.has_lean_files,
                review_count=pr.review_count,
                review_thread_count=pr.review_thread_count,
                comment_count=pr.comment_count,
                qualifies=pr.qualifies_for_extraction,
            )
            append_jsonl(settings.enrichment_dir / "pr_metadata.jsonl", pr)
            enriched += 1

        logger.info("Enriched %d/%d PRs", enriched, len(pending))

    return enriched
