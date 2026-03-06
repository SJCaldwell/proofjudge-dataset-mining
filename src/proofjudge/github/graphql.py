"""GraphQL queries for batch PR metadata fetching."""

import logging
from datetime import datetime
from typing import Any

from proofjudge.github.client import GitHubClient
from proofjudge.models.pr import PRFile, PRMetadata, detect_bors_status

logger = logging.getLogger(__name__)

# Batch query: 100 PRs per page, costs ~1 GraphQL point
PR_METADATA_BATCH_QUERY = """
query PRMetadataBatch($owner: String!, $repo: String!, $cursor: String) {
  rateLimit { remaining cost resetAt }
  repository(owner: $owner, name: $repo) {
    pullRequests(
      first: 100,
      after: $cursor,
      states: CLOSED,
      orderBy: { field: CREATED_AT, direction: DESC }
    ) {
      pageInfo { hasNextPage endCursor }
      totalCount
      nodes {
        number
        title
        state
        createdAt
        closedAt
        additions
        deletions
        changedFiles
        commits { totalCount }
        reviews { totalCount }
        comments { totalCount }
        reviewThreads { totalCount }
        labels(first: 15) {
          nodes { name }
        }
        files(first: 50) {
          nodes { path additions deletions }
        }
        headRefName
        headRefOid
        baseRefName
        author { login }
      }
    }
  }
}
"""

# Lookup specific PRs by number (up to ~20 per query)
PR_BY_NUMBER_FRAGMENT = """
fragment PRFields on PullRequest {
  number
  title
  state
  createdAt
  closedAt
  additions
  deletions
  changedFiles
  commits { totalCount }
  reviews { totalCount }
  comments { totalCount }
  reviewThreads { totalCount }
  labels(first: 15) {
    nodes { name }
  }
  files(first: 50) {
    nodes { path additions deletions }
  }
  headRefName
  headRefOid
  baseRefName
  author { login }
}
"""


def _parse_pr_node(node: dict[str, Any]) -> PRMetadata | None:
    """Parse a GraphQL PR node into a PRMetadata model."""
    author_data: dict[str, str] | None = node.get("author")
    author: str = author_data["login"] if author_data else "ghost"

    files_raw: dict[str, Any] = node.get("files", {}) or {}
    files_data: list[dict[str, Any]] = files_raw.get("nodes", []) or []
    files = [
        PRFile(
            path=str(f["path"]),
            additions=int(f["additions"]),
            deletions=int(f["deletions"]),
        )
        for f in files_data
    ]

    labels_raw: dict[str, Any] = node.get("labels", {}) or {}
    labels_data: list[dict[str, str]] = labels_raw.get("nodes", []) or []
    labels: list[str] = [label["name"] for label in labels_data]

    title: str = node["title"]
    state: str = node["state"]
    # GraphQL doesn't have a `merged` boolean we can rely on for Bors
    bors_status = detect_bors_status(title, state, merged=False)

    return PRMetadata(
        number=int(node["number"]),
        title=title,
        author=author,
        state=state,
        bors_status=bors_status,
        created_at=datetime.fromisoformat(str(node["createdAt"])),
        closed_at=datetime.fromisoformat(str(node["closedAt"])) if node.get("closedAt") else None,
        additions=int(node["additions"]),
        deletions=int(node["deletions"]),
        changed_files=int(node["changedFiles"]),
        commit_count=int(node["commits"]["totalCount"]),
        review_count=int(node["reviews"]["totalCount"]),
        comment_count=int(node["comments"]["totalCount"]),
        review_thread_count=int(node["reviewThreads"]["totalCount"]),
        labels=labels,
        files=files,
        head_ref=str(node.get("headRefName", "")),
        head_sha=str(node.get("headRefOid", "")),
        base_ref=str(node.get("baseRefName", "master")),
    )


async def fetch_pr_metadata_batch(
    client: GitHubClient,
    owner: str,
    repo: str,
    cursor: str | None = None,
) -> tuple[list[PRMetadata], str | None, bool, int]:
    """Fetch a batch of 100 closed PRs via GraphQL.

    Returns:
        (pr_list, next_cursor, has_next_page, total_count)
    """
    data = await client.graphql(
        PR_METADATA_BATCH_QUERY,
        variables={"owner": owner, "repo": repo, "cursor": cursor},
    )

    repo_data: dict[str, Any] = data["data"]["repository"]["pullRequests"]
    page_info: dict[str, Any] = repo_data["pageInfo"]
    total_count: int = int(repo_data["totalCount"])
    nodes: list[dict[str, Any]] = repo_data["nodes"]

    rate_limit: dict[str, Any] = data["data"].get("rateLimit", {})
    if rate_limit:
        logger.debug(
            "GraphQL rate limit: %s remaining, cost %s",
            rate_limit.get("remaining"),
            rate_limit.get("cost"),
        )

    prs: list[PRMetadata] = []
    for node in nodes:
        pr = _parse_pr_node(node)
        if pr is not None:
            prs.append(pr)

    next_cursor: str | None = str(page_info["endCursor"]) if page_info["hasNextPage"] else None
    has_next: bool = bool(page_info["hasNextPage"])
    return prs, next_cursor, has_next, total_count


async def fetch_prs_by_numbers(
    client: GitHubClient,
    owner: str,
    repo: str,
    numbers: list[int],
) -> list[PRMetadata]:
    """Fetch specific PRs by number using aliased GraphQL queries.

    Fetches up to 20 PRs per query to stay within GraphQL node limits.
    """
    results: list[PRMetadata] = []
    batch_size = 20

    for i in range(0, len(numbers), batch_size):
        batch = numbers[i : i + batch_size]
        aliases = "\n".join(f"pr{n}: pullRequest(number: {n}) {{ ...PRFields }}" for n in batch)
        query = f"""
        {PR_BY_NUMBER_FRAGMENT}
        query PRByNumbers($owner: String!, $repo: String!) {{
          repository(owner: $owner, name: $repo) {{
            {aliases}
          }}
        }}
        """
        data = await client.graphql(query, variables={"owner": owner, "repo": repo})
        repo_data: dict[str, Any] = data["data"]["repository"]

        for n in batch:
            node: dict[str, Any] | None = repo_data.get(f"pr{n}")
            if node is not None:
                pr = _parse_pr_node(node)
                if pr is not None:
                    results.append(pr)

    return results
