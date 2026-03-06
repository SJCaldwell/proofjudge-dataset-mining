"""Proof block and proof pair models."""

from enum import StrEnum

from pydantic import BaseModel, computed_field


class ProofBlockKind(StrEnum):
    """Kind of Lean 4 declaration."""

    THEOREM = "theorem"
    LEMMA = "lemma"
    EXAMPLE = "example"
    DEF = "def"
    INSTANCE = "instance"


class ProofBlock(BaseModel):
    """A single proof block extracted from a Lean 4 file."""

    kind: ProofBlockKind
    name: str | None = None  # None for `example`
    signature: str  # Declaration line(s) up to `:= by` or `:=`
    body: str  # The proof body
    full_text: str  # signature + body
    file_path: str
    start_line: int
    end_line: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def line_count(self) -> int:
        return self.full_text.count("\n") + 1


class ProofPair(BaseModel):
    """A matched initial/final pair of proofs for the same declaration."""

    pr_number: int
    file_path: str
    declaration_name: str | None
    declaration_kind: ProofBlockKind

    initial_proof: ProofBlock
    final_proof: ProofBlock

    @computed_field  # type: ignore[prop-decorator]
    @property
    def initial_line_count(self) -> int:
        return self.initial_proof.line_count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def final_line_count(self) -> int:
        return self.final_proof.line_count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def line_count_delta(self) -> int:
        return self.final_line_count - self.initial_line_count

    @computed_field  # type: ignore[prop-decorator]
    @property
    def signature_changed(self) -> bool:
        return self.initial_proof.signature != self.final_proof.signature


class PRParsingResult(BaseModel):
    """Result of parsing proof pairs from a single PR."""

    pr_number: int
    pairs: list[ProofPair]
    pair_count: int
