"""Review comment and extraction models."""

from datetime import datetime

from pydantic import BaseModel, computed_field

from proofjudge.models.pr import PRFile

BOT_LOGIN_SUFFIXES = ("[bot]",)
BOT_KNOWN_LOGINS = frozenset(
    {
        "github-actions[bot]",
        "mathlib-bors[bot]",
        "mathlib-merge-conflicts[bot]",
        "leanprover-bot",
    }
)


def is_bot_user(login: str) -> bool:
    """Check if a GitHub user login is a bot."""
    if login in BOT_KNOWN_LOGINS:
        return True
    return any(login.endswith(suffix) for suffix in BOT_LOGIN_SUFFIXES)


class ReviewComment(BaseModel):
    """An inline review comment attached to a specific file/line."""

    id: int
    author: str
    path: str
    position: int | None = None
    original_position: int | None = None
    body: str
    created_at: datetime
    in_reply_to_id: int | None = None
    review_id: int | None = None
    diff_hunk: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_bot(self) -> bool:
        return is_bot_user(self.author)


class IssueComment(BaseModel):
    """A top-level PR comment (not inline)."""

    id: int
    author: str
    body: str
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_bot(self) -> bool:
        return is_bot_user(self.author)


class FormalReview(BaseModel):
    """A formal GitHub review (APPROVED, CHANGES_REQUESTED, COMMENTED)."""

    id: int
    author: str
    state: str
    body: str
    submitted_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_bot(self) -> bool:
        return is_bot_user(self.author)


class CommitInfo(BaseModel):
    """A commit in the PR."""

    sha: str
    message: str
    author: str
    date: datetime


class PRExtraction(BaseModel):
    """Complete deep extraction for a single PR."""

    number: int
    reviews: list[FormalReview]
    review_comments: list[ReviewComment]
    issue_comments: list[IssueComment]
    commits: list[CommitInfo]
    files_changed: list[PRFile]
    first_commit_sha: str
    last_commit_sha: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def human_review_comments(self) -> list[ReviewComment]:
        return [c for c in self.review_comments if not c.is_bot]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def human_issue_comments(self) -> list[IssueComment]:
        return [c for c in self.issue_comments if not c.is_bot]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def human_reviews(self) -> list[FormalReview]:
        return [r for r in self.reviews if not r.is_bot]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_changes_requested(self) -> bool:
        return any(r.state == "CHANGES_REQUESTED" for r in self.human_reviews)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_human_comment_count(self) -> int:
        return (
            len(self.human_review_comments)
            + len(self.human_issue_comments)
            + len([r for r in self.human_reviews if r.body.strip()])
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reviewer_usernames(self) -> list[str]:
        authors: set[str] = set()
        for c in self.human_review_comments:
            authors.add(c.author)
        for r in self.human_reviews:
            authors.add(r.author)
        return sorted(authors)
