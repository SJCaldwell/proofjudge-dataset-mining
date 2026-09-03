"""PR discovery and metadata models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class DiscoverySource(StrEnum):
    """How a PR candidate was found."""

    FULL_SCAN = "full_scan"
    KEYWORD_SEARCH = "keyword_search"
    MANUAL = "manual"


class BorsMergeStatus(StrEnum):
    """Whether a PR was merged via Bors."""

    MERGED_BY_BORS = "merged_by_bors"
    CLOSED_NOT_MERGED = "closed_not_merged"
    GITHUB_MERGED = "github_merged"
    OPEN = "open"


BORS_TITLE_PREFIX = "[Merged by Bors] - "


def detect_bors_status(title: str, state: str, merged: bool) -> BorsMergeStatus:
    """Detect merge status from PR title and state.

    mathlib4 uses Bors, which closes PRs after merging. GitHub's merged_at
    field is always null for Bors merges, so we detect via title prefix.
    """
    if merged:
        return BorsMergeStatus.GITHUB_MERGED
    if state.upper() == "OPEN":
        return BorsMergeStatus.OPEN
    if title.startswith(BORS_TITLE_PREFIX):
        return BorsMergeStatus.MERGED_BY_BORS
    return BorsMergeStatus.CLOSED_NOT_MERGED


class PRCandidate(BaseModel):
    """Minimal PR record from discovery phase."""

    number: int
    source: DiscoverySource
    source_query: str | None = None
    discovered_at: datetime


class PRFile(BaseModel):
    """A file touched by a PR."""

    path: str
    additions: int
    deletions: int


# Paths that indicate infrastructure, not proof code
INFRA_PATH_PREFIXES = frozenset(
    {
        # build / CI / repo tooling
        "scripts/",
        ".github/",
        "test/",
        "lakefile",
        "lean-toolchain",
        "lake-manifest",
        # standalone tools shipped alongside mathlib — not mathematics
        "Cache/",
        "LongestPole/",
        "Shake/",
        "ImportGraph/",
        # Lean metaprogramming: linters, tactic implementations, elaborators.
        # These are real code but they are not proofs, and a proof-quality
        # rubric scores them very differently (measured: 31.6% aligned /
        # 52.6% inverted, against 60.6%/24.7% for actual proofs).
        "Mathlib/Tactic/",
        "Mathlib/Util/",
        "Mathlib/Lean/",
        "Mathlib/Mathport/",
        "Mathlib/Testing/",
    }
)


class PRMetadata(BaseModel):
    """Enriched PR metadata from GraphQL."""

    number: int
    title: str
    author: str
    state: str
    bors_status: BorsMergeStatus
    created_at: datetime
    closed_at: datetime | None
    additions: int
    deletions: int
    changed_files: int
    commit_count: int
    review_count: int
    comment_count: int
    review_thread_count: int
    labels: list[str]
    files: list[PRFile]
    head_ref: str
    head_sha: str
    base_ref: str

    @property
    def original_title(self) -> str:
        """Title without the Bors prefix."""
        if self.title.startswith(BORS_TITLE_PREFIX):
            return self.title[len(BORS_TITLE_PREFIX) :]
        return self.title

    @property
    def has_lean_files(self) -> bool:
        return any(f.path.endswith(".lean") for f in self.files)

    @property
    def is_proof_touching(self) -> bool:
        """Has .lean files that aren't infrastructure."""
        return any(
            f.path.endswith(".lean")
            and not any(f.path.startswith(prefix) for prefix in INFRA_PATH_PREFIXES)
            for f in self.files
        )

    @property
    def has_review_activity(self) -> bool:
        return self.review_thread_count >= 1 or self.review_count >= 1

    @property
    def qualifies_for_extraction(self) -> bool:
        """Passes all filters for deep extraction."""
        return (
            self.bors_status in (BorsMergeStatus.MERGED_BY_BORS, BorsMergeStatus.GITHUB_MERGED)
            and self.is_proof_touching
            and self.has_review_activity
            and self.additions >= 3
        )
