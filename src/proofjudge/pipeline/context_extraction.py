"""Phase 7: Extract full file contexts and base commit SHA for dataset PRs.

For each assembled PR, fetches:
1. The base commit SHA (parent of first commit — the mathlib version before the PR)
2. Full content of every .lean file touched by the PR at both first and last commit SHAs
"""

import asyncio
import logging

from proofjudge.config import Settings
from proofjudge.github.client import GitHubClient
from proofjudge.github.rest import fetch_commit_parents, fetch_file_content
from proofjudge.models.comments import PRExtraction
from proofjudge.models.context import FileSnapshot, PRContext
from proofjudge.storage.database import Database
from proofjudge.storage.jsonl import read_json_file, write_json_file

logger = logging.getLogger(__name__)


async def extract_context_for_pr(
    client: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    extraction: PRExtraction,
) -> PRContext:
    """Extract full file contexts and base commit for a single PR."""
    first_sha = extraction.first_commit_sha
    last_sha = extraction.last_commit_sha
    fetch_errors: list[str] = []

    # 1. Get base commit SHA (parent of first commit)
    base_sha = ""
    if first_sha:
        try:
            parents = await fetch_commit_parents(client, owner, repo, first_sha)
            if parents:
                base_sha = parents[0]
            else:
                fetch_errors.append(f"No parents found for first commit {first_sha}")
        except Exception as e:
            fetch_errors.append(f"Failed to fetch parents of {first_sha}: {e}")

    # 2. Collect .lean file paths from the PR
    lean_paths = [
        f.path for f in extraction.files_changed if f.path.endswith(".lean")
    ]

    # 3. Fetch file contents at both SHAs concurrently
    initial_tasks = [
        fetch_file_content(client, owner, repo, path, first_sha)
        for path in lean_paths
    ]
    final_tasks = [
        fetch_file_content(client, owner, repo, path, last_sha)
        for path in lean_paths
    ]

    all_results = await asyncio.gather(
        *initial_tasks, *final_tasks, return_exceptions=True
    )

    n = len(lean_paths)
    initial_results = all_results[:n]
    final_results = all_results[n:]

    initial_files: list[FileSnapshot] = []
    final_files: list[FileSnapshot] = []

    for i, path in enumerate(lean_paths):
        # Initial file
        init_result = initial_results[i]
        if isinstance(init_result, BaseException):
            fetch_errors.append(f"initial {path}: {init_result}")
            initial_files.append(FileSnapshot(path=path, content=None))
        else:
            initial_files.append(FileSnapshot(path=path, content=init_result))

        # Final file
        final_result = final_results[i]
        if isinstance(final_result, BaseException):
            fetch_errors.append(f"final {path}: {final_result}")
            final_files.append(FileSnapshot(path=path, content=None))
        else:
            final_files.append(FileSnapshot(path=path, content=final_result))

    return PRContext(
        pr_number=pr_number,
        base_commit_sha=base_sha,
        first_commit_sha=first_sha,
        last_commit_sha=last_sha,
        initial_files=initial_files,
        final_files=final_files,
        lean_file_count=len(lean_paths),
        fetch_errors=fetch_errors,
    )


async def run_context_extraction(
    client: GitHubClient,
    db: Database,
    settings: Settings,
    limit: int | None = None,
    concurrency: int = 3,
) -> int:
    """Run context extraction for all assembled PRs.

    Returns the number of PRs successfully processed.
    """
    pending = db.get_prs_needing_context_extraction(limit=limit)
    if not pending:
        logger.info("No PRs need context extraction")
        return 0

    logger.info("Extracting contexts for %d PRs...", len(pending))
    semaphore = asyncio.Semaphore(concurrency)
    extracted = 0

    async def extract_with_semaphore(pr_number: int) -> bool:
        async with semaphore:
            try:
                # Load extraction data for SHAs and file list
                extraction_path = settings.extraction_dir / f"pr_{pr_number}.json"
                extraction = read_json_file(extraction_path, PRExtraction)
                if extraction is None:
                    logger.warning("No extraction data for PR #%d", pr_number)
                    db.record_error(pr_number, "context: no extraction data")
                    return False

                context = await extract_context_for_pr(
                    client,
                    settings.github_owner,
                    settings.github_repo,
                    pr_number,
                    extraction,
                )

                # Write context file
                output_path = settings.contexts_dir / f"pr_{pr_number}.json"
                write_json_file(output_path, context)

                # Mark complete
                db.mark_phase_complete(pr_number, "contexts_extracted_at")

                logger.info(
                    "Extracted context for PR #%d: %d .lean files, base=%s%s",
                    pr_number,
                    context.lean_file_count,
                    context.base_commit_sha[:12] if context.base_commit_sha else "N/A",
                    f", {len(context.fetch_errors)} errors" if context.fetch_errors else "",
                )
                return True
            except Exception as e:
                db.record_error(pr_number, f"context: {e}")
                logger.error("Failed context extraction for PR #%d: %s", pr_number, e)
                return False

    tasks = [extract_with_semaphore(pr) for pr in pending]
    results = await asyncio.gather(*tasks)
    extracted = sum(1 for r in results if r)

    logger.info(
        "Context extraction complete: %d/%d PRs succeeded", extracted, len(pending)
    )
    return extracted
