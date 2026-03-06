"""Phase 3: Deep extraction of reviews, comments, commits, and file diffs."""

import asyncio
import logging

from proofjudge.config import Settings
from proofjudge.github.client import GitHubClient
from proofjudge.github.rest import (
    fetch_commits,
    fetch_issue_comments,
    fetch_pr_files,
    fetch_review_comments,
    fetch_reviews,
)
from proofjudge.models.comments import PRExtraction
from proofjudge.storage.database import Database
from proofjudge.storage.jsonl import write_json_file

logger = logging.getLogger(__name__)


async def extract_single_pr(
    client: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
) -> PRExtraction:
    """Extract all deep data for a single PR."""
    # Fetch all data sources concurrently
    review_comments, issue_comments, reviews, commits, files = await asyncio.gather(
        fetch_review_comments(client, owner, repo, pr_number),
        fetch_issue_comments(client, owner, repo, pr_number),
        fetch_reviews(client, owner, repo, pr_number),
        fetch_commits(client, owner, repo, pr_number),
        fetch_pr_files(client, owner, repo, pr_number),
    )

    # Determine first and last commit SHAs
    first_sha = commits[0].sha if commits else ""
    last_sha = commits[-1].sha if commits else ""

    return PRExtraction(
        number=pr_number,
        reviews=reviews,
        review_comments=review_comments,
        issue_comments=issue_comments,
        commits=commits,
        files_changed=files,
        first_commit_sha=first_sha,
        last_commit_sha=last_sha,
    )


async def run_extraction(
    client: GitHubClient,
    db: Database,
    settings: Settings,
    limit: int | None = None,
    concurrency: int | None = None,
) -> int:
    """Run deep extraction for all qualifying PRs.

    Returns the number of PRs successfully extracted.
    """
    pending = db.get_prs_needing_extraction(limit=limit)
    if not pending:
        logger.info("No PRs need extraction")
        return 0

    logger.info("Extracting %d PRs...", len(pending))
    max_concurrent = concurrency or settings.extraction_concurrency
    semaphore = asyncio.Semaphore(max_concurrent)
    extracted = 0

    async def extract_with_semaphore(pr_number: int) -> bool:
        async with semaphore:
            try:
                extraction = await extract_single_pr(
                    client,
                    settings.github_owner,
                    settings.github_repo,
                    pr_number,
                )

                # Write per-PR extraction file
                output_path = settings.extraction_dir / f"pr_{pr_number}.json"
                write_json_file(output_path, extraction)

                # Mark complete in database
                db.mark_phase_complete(pr_number, "extracted_at")

                human_count = extraction.total_human_comment_count
                logger.info(
                    "Extracted PR #%d: %d human comments, %d reviewers",
                    pr_number,
                    human_count,
                    len(extraction.reviewer_usernames),
                )
                return True
            except Exception as e:
                db.record_error(pr_number, str(e))
                logger.error("Failed to extract PR #%d: %s", pr_number, e)
                return False

    # Process all PRs with bounded concurrency
    tasks = [extract_with_semaphore(pr) for pr in pending]
    results = await asyncio.gather(*tasks)
    extracted = sum(1 for r in results if r)

    logger.info("Extraction complete: %d/%d PRs succeeded", extracted, len(pending))
    return extracted
