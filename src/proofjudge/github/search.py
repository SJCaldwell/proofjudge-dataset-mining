"""GitHub search API with keyword strategies and cursor tracking."""

import logging
from typing import Any

from proofjudge.github.client import GitHubClient
from proofjudge.storage.database import Database

logger = logging.getLogger(__name__)

# High-signal keyword queries for finding PRs with style-related review feedback
KEYWORD_QUERIES: list[tuple[str, str]] = [
    (
        "golf",
        'repo:leanprover-community/mathlib4 type:pr is:closed "golf" in:comments',
    ),
    (
        "can_be_golfed",
        'repo:leanprover-community/mathlib4 type:pr is:closed "can be golfed" in:comments',
    ),
    (
        "readability",
        'repo:leanprover-community/mathlib4 type:pr is:closed "readability" in:comments',
    ),
    (
        "idiomatic",
        'repo:leanprover-community/mathlib4 type:pr is:closed "idiomatic" in:comments',
    ),
    (
        "nonterminal_simp",
        'repo:leanprover-community/mathlib4 type:pr is:closed "nonterminal simp" in:comments',
    ),
    (
        "changes_requested",
        "repo:leanprover-community/mathlib4 type:pr is:closed review:changes_requested",
    ),
    (
        "simplify",
        'repo:leanprover-community/mathlib4 type:pr is:closed "simplify" in:comments',
    ),
]


async def run_keyword_searches(
    client: GitHubClient,
    db: Database,
    limit_per_query: int | None = None,
) -> int:
    """Run all keyword searches and upsert discovered PRs.

    Returns total number of unique PRs discovered.
    """
    total_new = 0

    for query_key, query_string in KEYWORD_QUERIES:
        last_page = db.get_search_cursor(query_key)
        if last_page == -1:
            logger.info("Search '%s' already completed, skipping", query_key)
            continue

        page = last_page + 1
        found_in_query = 0

        while True:
            logger.info("Searching '%s' page %d...", query_key, page)
            response = await client.search(query_string, page=page, per_page=100)
            data: dict[str, Any] = response.json()

            total_count: int = int(data.get("total_count", 0))
            items: list[dict[str, Any]] = data.get("items", [])

            if not items:
                db.update_search_cursor(query_key, page, total_count, completed=True)
                break

            for item in items:
                pr_number: int = int(item["number"])
                db.upsert_candidate(pr_number, "keyword_search", query_key)
                found_in_query += 1

            db.update_search_cursor(query_key, page, total_count, completed=False)

            if limit_per_query and found_in_query >= limit_per_query:
                logger.info("Hit limit for '%s' at %d PRs", query_key, found_in_query)
                break

            # Search API returns max 1000 results (10 pages of 100)
            if page >= 10 or len(items) < 100:
                db.update_search_cursor(query_key, page, total_count, completed=True)
                break

            page += 1

        logger.info(
            "Search '%s': found %d PRs (total_count=%d)",
            query_key,
            found_in_query,
            total_count,
        )
        total_new += found_in_query

    return total_new
