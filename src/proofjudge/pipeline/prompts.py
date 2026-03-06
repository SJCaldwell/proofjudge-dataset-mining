"""Prompt engineering for LLM-based proof pair classification and summarization."""

from proofjudge.models.comments import PRExtraction, ReviewComment
from proofjudge.models.proof import ProofPair

SYSTEM_PROMPT = """\
You are a Lean 4 proof quality judge. You classify proof changes from mathlib4 \
pull requests into one of three categories and summarize why the proof was changed.

## Categories

- **HIGH_VALUE**: The proof body changed in a meaningful way that reflects \
proof style, tactic choice, readability, or generality improvements. The change \
is driven by reviewer feedback or represents a genuine proof quality improvement. \
These are the pairs we want in our dataset.

- **LOW_VALUE**: The change is trivial, mechanical, or unrelated to proof quality. \
Examples: whitespace-only changes, renaming without substance, automated migrations \
(e.g. refine' -> refine), or changes that only affect the declaration signature \
without meaningfully changing the proof strategy.

- **CONTEXTUAL**: The proof body changed, but primarily because of external factors \
rather than proof quality feedback. Examples: adapting to an API change in another file, \
updating to use a renamed lemma, or adjusting to a new typeclass instance. The proof \
writer had no meaningful choice in how to rewrite the proof.

## Output Format

Respond with a JSON object (no markdown code fences) containing:
{
  "verdict": "HIGH_VALUE" | "LOW_VALUE" | "CONTEXTUAL",
  "verdict_reasoning": "1-2 sentence explanation of the classification",
  "summary": "2-4 sentence description of what changed and why, suitable as training data",
  "categories": ["list", "of", "feedback_categories"],
  "key_changes": ["specific tactic/strategy changes made"],
  "reviewer_quotes": ["exact quotes from reviewers that motivated the change"],
  "has_explicit_review_feedback": true/false,
  "confidence": 0.0 to 1.0
}

Valid categories: tactic_hygiene, generality, proof_structure, readability, naming, \
performance, simp_lemmas, api_design, other

## Examples

### Example 1: HIGH_VALUE

PR Title: "golf Nat.multichoose proofs"
Declaration: `sum_range_multichoose`
Initial proof (10 lines):
```
theorem sum_range_multichoose (n : ℕ) :
    (∑ k ∈ Finset.range n, (n - k).multichoose k) = n.fib (n + 1) := by
  induction n with
  | zero => simp
  | succ n ih =>
    rw [Finset.sum_range_succ, Nat.sub_self, multichoose_zero]
    conv_lhs => arg 1; ext k; rw [succ_sub (Finset.mem_range.mp ‹_›)]
    rw [← Finset.sum_range_succ]
    simp [ih, fib_add_two]
```
Final proof (5 lines):
```
theorem sum_range_multichoose (n : ℕ) :
    (∑ k ∈ Finset.range n, (n - k).multichoose k) = n.fib (n + 1) := by
  induction n with
  | zero => simp
  | succ n ih => simp_all [Finset.sum_range_succ', fib_add_two]
```
Review context: "these can be golfed quite a bit"

Response:
{
  "verdict": "HIGH_VALUE",
  "verdict_reasoning": "Reviewer explicitly requested golfing; proof was halved by \
using simp_all with the right lemma set instead of manual rewriting.",
  "summary": "The inductive step was simplified from 5 lines of manual rewriting \
(conv_lhs, explicit rw steps) to a single simp_all call with Finset.sum_range_succ' \
and fib_add_two. This demonstrates that choosing the right simp lemma set can \
eliminate manual proof steps entirely.",
  "categories": ["tactic_hygiene", "simp_lemmas", "proof_structure"],
  "key_changes": ["Replaced manual conv_lhs/rw chain with simp_all", \
"Used Finset.sum_range_succ' instead of sum_range_succ"],
  "reviewer_quotes": ["these can be golfed quite a bit"],
  "has_explicit_review_feedback": true,
  "confidence": 0.95
}

### Example 2: CONTEXTUAL

PR Title: "[Merged by Bors] - refactor: rename Ordinal arithmetic operations"
Declaration: `Ordinal.add_lt_add_iff_left`
Initial proof:
```
theorem add_lt_add_iff_left (a : Ordinal) {b c : Ordinal} : a + b < a + c ↔ b < c := by
  rw [add_def a b, add_def a c]
  exact Type.add_lt_add_iff_left ...
```
Final proof:
```
theorem add_lt_add_iff_left (a : Ordinal) {b c : Ordinal} : a + b < a + c ↔ b < c := by
  rw [hAdd_def a b, hAdd_def a c]
  exact Type.add_lt_add_iff_left ...
```
Review context: (no comments on this specific declaration)

Response:
{
  "verdict": "CONTEXTUAL",
  "verdict_reasoning": "The only change is add_def -> hAdd_def, which is a mechanical \
rename from another PR. No proof strategy changed.",
  "summary": "The proof was updated to use the renamed lemma hAdd_def (previously \
add_def) as part of the Ordinal arithmetic refactor. The proof structure and strategy \
are identical.",
  "categories": ["api_design"],
  "key_changes": ["add_def renamed to hAdd_def"],
  "reviewer_quotes": [],
  "has_explicit_review_feedback": false,
  "confidence": 0.9
}
"""

# Maximum chars of review context to include in the user prompt
_MAX_REVIEW_CONTEXT_CHARS = 12000


def format_review_context(
    pair: ProofPair,
    extraction: PRExtraction,
    max_chars: int = _MAX_REVIEW_CONTEXT_CHARS,
) -> str:
    """Build relevance-filtered review context for a proof pair.

    Priority ordering:
    1. Inline comments on same file with declaration name in diff_hunk
    2. Inline comments on same file
    3. Formal reviews with non-empty body + issue comments
    """
    # Priority 1: Inline comments targeting this declaration
    p1_comments: list[str] = []
    # Priority 2: Inline comments on same file
    p2_comments: list[str] = []
    # Priority 3: Other human feedback
    p3_comments: list[str] = []

    for c in extraction.human_review_comments:
        formatted = _format_review_comment(c)
        is_same_file = c.path == pair.file_path
        has_decl = pair.declaration_name and pair.declaration_name in c.diff_hunk
        if is_same_file and has_decl:
            p1_comments.append(formatted)
        elif is_same_file:
            p2_comments.append(formatted)

    for r in extraction.human_reviews:
        if r.body.strip():
            p3_comments.append(f"[Formal review by @{r.author} ({r.state})] {r.body.strip()}")

    for c in extraction.human_issue_comments:
        body = c.body.strip()
        # Skip bors commands and short approval messages
        if body.startswith("bors") or len(body) < 20:
            continue
        p3_comments.append(f"[Comment by @{c.author}] {body}")

    # Assemble within budget
    lines: list[str] = []
    budget = max_chars

    for group in [p1_comments, p2_comments, p3_comments]:
        for comment in group:
            if len(comment) > budget:
                break
            lines.append(comment)
            budget -= len(comment) + 1  # +1 for newline
        if budget <= 0:
            break

    if not lines:
        return "(no reviewer comments found)"

    return "\n\n".join(lines)


def _format_review_comment(c: ReviewComment) -> str:
    """Format a single inline review comment for the prompt."""
    location = f"{c.path}"
    if c.position is not None:
        location += f":{c.position}"
    return f"[Inline comment by @{c.author} on {location}] {c.body.strip()}"


def build_user_prompt(
    pair: ProofPair,
    extraction: PRExtraction,
    pr_title: str,
) -> str:
    """Assemble the user prompt for a single proof pair classification."""
    review_context = format_review_context(pair, extraction)

    decl_name = pair.declaration_name or "(unnamed)"

    return f"""\
PR Title: {pr_title}
PR #{extraction.number}
File: {pair.file_path}
Declaration: `{decl_name}` ({pair.declaration_kind.value})
Signature changed: {pair.signature_changed}

## Initial Proof ({pair.initial_line_count} lines)
```lean
{pair.initial_proof.full_text}
```

## Final Proof ({pair.final_line_count} lines)
```lean
{pair.final_proof.full_text}
```

## Reviewer Comments
{review_context}
"""
