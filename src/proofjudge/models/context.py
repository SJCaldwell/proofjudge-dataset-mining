"""Context extraction models for full file snapshots and base commit info."""

from pydantic import BaseModel


class FileSnapshot(BaseModel):
    """A file's content at a specific commit SHA."""

    path: str
    content: str | None  # None if file doesn't exist at this commit


class PRContext(BaseModel):
    """Full file context for a PR: base commit + file contents at both SHAs."""

    pr_number: int
    base_commit_sha: str
    first_commit_sha: str
    last_commit_sha: str
    initial_files: list[FileSnapshot]
    final_files: list[FileSnapshot]
    lean_file_count: int
    fetch_errors: list[str]
