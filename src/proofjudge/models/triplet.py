"""Final triplet and HuggingFace dataset models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from proofjudge.models.proof import ProofBlockKind


class FeedbackCategory(StrEnum):
    """Categories of reviewer feedback."""

    TACTIC_HYGIENE = "tactic_hygiene"
    GENERALITY = "generality"
    PROOF_STRUCTURE = "proof_structure"
    READABILITY = "readability"
    NAMING = "naming"
    PERFORMANCE = "performance"
    SIMP_LEMMAS = "simp_lemmas"
    API_DESIGN = "api_design"
    OTHER = "other"


class QualityVerdict(StrEnum):
    """LLM classification of a proof pair's value for the dataset."""

    HIGH_VALUE = "HIGH_VALUE"
    LOW_VALUE = "LOW_VALUE"
    CONTEXTUAL = "CONTEXTUAL"


class SummarizedFeedback(BaseModel):
    """LLM-generated summary of reviewer feedback for one proof pair."""

    summary: str
    categories: list[FeedbackCategory]
    key_changes: list[str]
    reviewer_quotes: list[str]
    confidence: float


class PairSummarization(BaseModel):
    """Full LLM classification + summarization result for a single proof pair."""

    declaration_name: str | None
    file_path: str
    verdict: QualityVerdict
    verdict_reasoning: str
    summary: str
    categories: list[FeedbackCategory]
    key_changes: list[str]
    reviewer_quotes: list[str]
    has_explicit_review_feedback: bool
    confidence: float
    model: str
    input_tokens: int
    output_tokens: int


class PRSummarizationResult(BaseModel):
    """Aggregated summarization results for all pairs in a single PR."""

    pr_number: int
    pair_results: list[PairSummarization]
    high_value_count: int
    low_value_count: int
    contextual_count: int
    total_input_tokens: int
    total_output_tokens: int


class ProofTriplet(BaseModel):
    """The final output triplet for one proof."""

    # Identity
    pr_number: int
    file_path: str
    declaration_name: str | None
    declaration_kind: ProofBlockKind

    # The triplet
    initial_proof: str
    final_proof: str
    rejection_summary: str

    # Rich metadata
    feedback: SummarizedFeedback

    # PR context
    pr_title: str
    pr_author: str
    reviewers: list[str]
    pr_created_at: datetime
    pr_closed_at: datetime | None
    review_duration_days: float


class HuggingFaceRow(BaseModel):
    """Flat schema for HuggingFace datasets export.

    This is the public-facing schema. It must be stable across versions.
    """

    # Primary triplet
    initial_proof: str
    final_proof: str
    rejection_reasons: str

    # Structured metadata
    pr_number: int
    pr_url: str
    file_path: str
    declaration_name: str
    declaration_kind: str

    # Feedback details
    feedback_categories: list[str]
    key_changes: list[str]

    # Context
    pr_title: str
    pr_author: str
    reviewers: list[str]
    created_at: str
    closed_at: str
    review_duration_days: float

    # Metrics
    initial_line_count: int
    final_line_count: int
    line_count_delta: int
    signature_changed: bool

    # Provenance
    dataset_version: str
    extraction_date: str
