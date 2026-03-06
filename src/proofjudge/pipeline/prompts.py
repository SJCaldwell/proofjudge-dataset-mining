"""Prompt engineering for LLM-based proof pair classification and summarization."""

from proofjudge.models.comments import PRExtraction, ReviewComment
from proofjudge.models.proof import ProofPair

SYSTEM_PROMPT = """\
You are a Lean 4 proof quality judge. You classify proof changes from mathlib4 \
pull requests. Our goal is to build a dataset of proofs that were *correct but \
had structural or style issues* that reviewers caught — we want to train a model \
to identify these issues.

## Categories

- **HIGH_VALUE**: The proof *approach or strategy* fundamentally changed in a way \
that reflects proof style, tactic choice, structure, or generality improvements. \
The key test: could a proof quality judge learn something useful from this pair? \
A HIGH_VALUE change means the initial proof had a genuine structural deficiency \
(verbose tactics, missed automation, poor decomposition, unnecessary hypotheses) \
that the final proof fixes.

- **LOW_VALUE**: The change is trivial, mechanical, or cosmetic. It does not \
reflect a meaningful proof quality difference. Examples:
  - Whitespace, formatting, or comment-only changes
  - Adding/removing `only` from `simp`/`simpa` without changing the lemma set
  - Reordering `have`/`let` statements without changing proof logic
  - Automated migrations (e.g. `refine'` → `refine`)
  - Signature-only changes that don't affect the proof body
  - Minor bracket/parenthesis adjustments

- **CONTEXTUAL**: The proof body changed, but the change was *forced by external \
factors* — the proof writer had no meaningful choice in how to adapt. Examples:
  - Substituting one lemma name for another (e.g. `le_div` → `mul_le_iff_le_div`) \
— even when the new name is "better", if the proof structure is identical, this \
is just an API rename
  - Adapting to a changed definition or renamed API, whether from another PR or \
from the same PR
  - Adjusting to a new typeclass instance or changed import
  - Replacing `foo` with `Foo.foo` (namespace change) without strategy change

**Critical distinction**: If the only differences between the initial and final \
proof are *which lemma names appear* in otherwise identical tactic calls (rw, simp, \
exact, apply), that is CONTEXTUAL regardless of whether the new names are clearer. \
The proof *strategy* (which tactics are used, how the proof is decomposed, what \
automation is leveraged) must change for HIGH_VALUE.

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

### Example 1: HIGH_VALUE — proof strategy fundamentally changed

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
replacing a 5-line manual rewrite chain with a single simp_all call.",
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

### Example 2: CONTEXTUAL — lemma name substitution, same proof structure

PR Title: "refactor: rename Ordinal arithmetic operations"
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
  "verdict_reasoning": "The only change is add_def -> hAdd_def, a mechanical lemma \
rename. The proof structure (rw then exact) is identical.",
  "summary": "The proof was updated to use the renamed lemma hAdd_def (previously \
add_def) as part of the Ordinal arithmetic refactor. The proof structure and strategy \
are identical.",
  "categories": ["api_design"],
  "key_changes": ["add_def renamed to hAdd_def"],
  "reviewer_quotes": [],
  "has_explicit_review_feedback": false,
  "confidence": 0.9
}

### Example 3: CONTEXTUAL — same PR introduces new lemma names, proof structure unchanged

PR Title: "refactor(Ordinal): replace div/mod lemmas with iff variants"
Declaration: `Ordinal.div_le_left`
Initial proof:
```
theorem div_le_left (a : Ordinal) {b : Ordinal} (hb : b ≠ 0) :
    a / b ≤ a := by
  rw [le_div hb, mul_one]
  exact le_refl a
```
Final proof:
```
theorem div_le_left (a : Ordinal) {b : Ordinal} (hb : b ≠ 0) :
    a / b ≤ a := by
  rw [← mul_le_iff_le_div hb, mul_one]
  exact le_refl a
```
Review context: "I introduced mul_le_iff_le_div as a cleaner name for le_div"

Response:
{
  "verdict": "CONTEXTUAL",
  "verdict_reasoning": "le_div was renamed to mul_le_iff_le_div within the same PR. \
The proof uses the same rw-then-exact structure with an equivalent lemma.",
  "summary": "The proof was updated to use mul_le_iff_le_div (replacing le_div) as \
part of a lemma renaming refactor within the same PR. The proof structure and \
strategy are identical — only the lemma name changed.",
  "categories": ["api_design"],
  "key_changes": ["le_div renamed to mul_le_iff_le_div"],
  "reviewer_quotes": [],
  "has_explicit_review_feedback": false,
  "confidence": 0.95
}

### Example 4: LOW_VALUE — trivial tactic tweak

PR Title: "style: avoid terminal simp only"
Declaration: `Ordinal.mul_div_cancel`
Initial proof:
```
theorem mul_div_cancel (a : Ordinal) {b : Ordinal} (hb : b ≠ 0) :
    a * b / b = a := by
  simpa only [add_zero, zero_div] using mul_add_div a (zero_div b ▸ Ordinal.zero_lt_of_ne_zero hb)
```
Final proof:
```
theorem mul_div_cancel (a : Ordinal) {b : Ordinal} (hb : b ≠ 0) :
    a * b / b = a := by
  simpa using mul_add_div a (zero_div b ▸ Ordinal.zero_lt_of_ne_zero hb)
```

Response:
{
  "verdict": "LOW_VALUE",
  "verdict_reasoning": "The only change is removing 'only [add_zero, zero_div]' from \
simpa. The proof structure and strategy are identical.",
  "summary": "The explicit lemma list was removed from simpa, letting the tactic \
find the same lemmas automatically. This is a trivial style preference that does \
not change the proof approach.",
  "categories": ["tactic_hygiene"],
  "key_changes": ["Removed explicit only clause from simpa"],
  "reviewer_quotes": [],
  "has_explicit_review_feedback": false,
  "confidence": 0.95
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
