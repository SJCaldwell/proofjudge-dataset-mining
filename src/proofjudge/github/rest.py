"""REST API wrappers for deep PR data extraction."""

import base64
import logging
from datetime import datetime
from typing import Any

from proofjudge.github.client import GitHubClient
from proofjudge.models.comments import CommitInfo, FormalReview, IssueComment, ReviewComment
from proofjudge.models.pr import PRFile

logger = logging.getLogger(__name__)


def _get_login(item: dict[str, Any], key: str = "user") -> str:
    """Extract login from a nested user object, defaulting to 'ghost'."""
    user: dict[str, str] | None = item.get(key)
    if user is not None:
        return str(user["login"])
    return "ghost"


async def fetch_review_comments(
    client: GitHubClient, owner: str, repo: str, pr_number: int
) -> list[ReviewComment]:
    """Fetch all inline review comments for a PR."""
    items = await client.rest_get_all_pages(f"/repos/{owner}/{repo}/pulls/{pr_number}/comments")
    return [
        ReviewComment(
            id=int(item["id"]),
            author=_get_login(item),
            path=str(item["path"]),
            position=item.get("position"),
            original_position=item.get("original_position"),
            body=str(item.get("body", "")),
            created_at=datetime.fromisoformat(str(item["created_at"])),
            in_reply_to_id=item.get("in_reply_to_id"),
            review_id=item.get("pull_request_review_id"),
            diff_hunk=str(item.get("diff_hunk", "")),
        )
        for item in items
    ]


async def fetch_issue_comments(
    client: GitHubClient, owner: str, repo: str, pr_number: int
) -> list[IssueComment]:
    """Fetch all top-level comments on a PR."""
    items = await client.rest_get_all_pages(f"/repos/{owner}/{repo}/issues/{pr_number}/comments")
    return [
        IssueComment(
            id=int(item["id"]),
            author=_get_login(item),
            body=str(item.get("body", "")),
            created_at=datetime.fromisoformat(str(item["created_at"])),
        )
        for item in items
    ]


async def fetch_reviews(
    client: GitHubClient, owner: str, repo: str, pr_number: int
) -> list[FormalReview]:
    """Fetch all formal reviews on a PR."""
    items = await client.rest_get_all_pages(f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews")
    return [
        FormalReview(
            id=int(item["id"]),
            author=_get_login(item),
            state=str(item["state"]),
            body=str(item.get("body", "")),
            submitted_at=datetime.fromisoformat(str(item["submitted_at"])),
        )
        for item in items
    ]


async def fetch_commits(
    client: GitHubClient, owner: str, repo: str, pr_number: int
) -> list[CommitInfo]:
    """Fetch all commits in a PR."""
    items = await client.rest_get_all_pages(f"/repos/{owner}/{repo}/pulls/{pr_number}/commits")
    results: list[CommitInfo] = []
    for item in items:
        commit_data: dict[str, Any] = item["commit"]
        author_data: dict[str, Any] = commit_data["author"]
        login = _get_login(item, "author")
        if login == "ghost":
            login = str(author_data.get("name", "ghost"))
        results.append(
            CommitInfo(
                sha=str(item["sha"]),
                message=str(commit_data["message"]),
                author=login,
                date=datetime.fromisoformat(str(author_data["date"])),
            )
        )
    return results


async def fetch_pr_files(
    client: GitHubClient, owner: str, repo: str, pr_number: int
) -> list[PRFile]:
    """Fetch the list of files changed in a PR."""
    items = await client.rest_get_all_pages(f"/repos/{owner}/{repo}/pulls/{pr_number}/files")
    return [
        PRFile(
            path=str(item["filename"]),
            additions=int(item["additions"]),
            deletions=int(item["deletions"]),
        )
        for item in items
    ]


async def fetch_commit_parents(
    client: GitHubClient, owner: str, repo: str, sha: str
) -> list[str]:
    """Fetch the parent commit SHAs for a given commit."""
    response = await client.rest_get(f"/repos/{owner}/{repo}/commits/{sha}")
    data: dict[str, Any] = response.json()
    parents: list[dict[str, Any]] = data.get("parents", [])
    return [str(p["sha"]) for p in parents]


async def fetch_file_content(
    client: GitHubClient, owner: str, repo: str, path: str, ref: str
) -> str | None:
    """Fetch the content of a file at a specific commit SHA.

    Returns None if the file doesn't exist at that ref.
    """
    try:
        response = await client.rest_get(
            f"/repos/{owner}/{repo}/contents/{path}",
            ref=ref,
        )
        data: dict[str, Any] = response.json()
        if data.get("encoding") == "base64" and data.get("content"):
            content_b64: str = data["content"]
            return base64.b64decode(content_b64).decode("utf-8")
        return None
    except Exception:
        logger.debug("Could not fetch %s at %s", path, ref)
        return None
