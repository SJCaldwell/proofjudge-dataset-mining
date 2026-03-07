# Proof Improvement Rubrics — Running Tally

Patterns observed in HIGH_VALUE proof pairs that would make good rubrics for a
proof quality judge. Each rubric describes a recognizable structural deficiency
in the initial proof.

## 1. Direct Lemma Application Over Manual Reconstruction
**Instances seen: 7**

The initial proof manually constructs what an existing library lemma already
provides. A good judge would recognize "this is reinventing the wheel."

- **single_eq_zero_iff** (PR #7905): Manual `constructor`/`contrapose!`/`simp`
  replaced by `map_eq_zero_iff _ <| single_injective a` (5→2 lines)
- **singleton_seq** (PR #7236): `Set.ext <| by simp` replaced by direct
  `image2_singleton_left` (same line count, cleaner)
- **uniformContinuous_toFun** (PR #13349): Manual witness extraction via
  `sUnion_eq_univ_iff.mp` replaced by `uniformContinuous_eval` (6→4 lines)
- **gc_lowerClosure_coe** (PR #2508): Manual GC construction with `⟨fun h =>
  ..., fun h => ...⟩` replaced by direct `lowerClosure_le` (4→2 lines)
- **gc_upperClosure_coe** (PR #2508): Same pattern with `le_upperClosure`
  (4→3 lines)
- **baseChange** (PR #6035): 9-line manual LinearMap construction replaced by
  `AlgebraTensorModule.map LinearMap.id f` (9→2 lines)
- **notBelow_isOpen** (PR #5805): Verbose 8-line monotonicity proof replaced
  by concise `fun x z hle => mt hle.trans` (13→5 lines)

## 2. Pattern Matching Over Tactic-Mode Induction
**Instances seen: 1**

When all induction cases are term-mode proofs, pattern matching is cleaner
than `induction ... with | case => ...` syntax.

- **perm_insertNth** (PR #254): 15→9 lines, tactic-mode `induction`/`cases`
  replaced by term-mode `match` with pattern matching

## 3. Structural Insight Collapsing Case Analysis
**Instances seen: 1**

Recognizing a mathematical property (like Subsingleton, Unique) that eliminates
entire branches of case analysis.

- **op_norm_extend_le** (PR #5742): 26→18 lines. Recognized that N ≤ 0 forces
  `Unique E`, collapsing the proof via `Subsingleton.elim`

## 4. Automation Over Manual Proof Steps (Golfing)
**Instances seen: 2**

The initial proof manually sequences rewrite steps that `simp`/`simp_all`/`omega`
can find automatically with the right lemma hints.

- **sum_range_multichoose** (PR #33656): 10→5 lines, manual `conv_lhs`/`rw` chain
  replaced by `simp_all [Finset.sum_range_succ', fib_add_two]`
- **isEdgeReachable_one** (PR #32870): 11→2 lines, manual constructor replaced
  by `simp` with right lemmas

## 5. Term Mode Over Unnecessary Tactic Mode
**Instances seen: 1**

When the proof is a direct application or composition, tactic mode
(`by apply/exact`) adds unnecessary overhead.

- **cellFrontier_subset_complex** (PR #20287): `apply subset_trans` →
  `.trans` dot notation (3→3 lines, but cleaner)

## 6. Choosing Better Tactic Variants
**Instances seen: 1**

Using a more appropriate tactic variant that handles the goal more directly.

- **measure_eq_measure_preimage** (PR #7795): Manual `eq_or_lt_of_le` case
  analysis replaced by `inter_distrib_left`, `preimage_union` set operations
  (50→44 lines)

## 7. Recognizing Definitional Equality
**Instances seen: 1**

The initial proof uses explicit reasoning where the goal is actually
definitionally true (`rfl`) or follows from a simpler computation.

- **coe_eq_algebraMap** (PR #5742): Complex double-simp chain (5 lines)
  replaced by `rfl` for the defeq case + clean `mul_comm` for the non-defeq
  case (5→5 lines, but structurally cleaner)

## 8. Named Arguments Over Positional Underscores
**Instances seen: 2**

Using `(α := αᵒᵈ)` named arguments instead of `@ ... _ _ _ _ _` positional
application. Makes code more robust and readable.

- **frontier_Ici_subset** (PR #6107): `@frontier_Iic_subset αᵒᵈ _ _ _ _` →
  `frontier_Iic_subset (α := αᵒᵈ) _` (2→2 lines)
- **IsGLB.isLUB_of_tendsto** (PR #6107): Same pattern with `(γ := γᵒᵈ)`

## 9. Galois Connection / Order-Theoretic Lemmas
**Instances seen: 1**

Using order-theoretic framework lemmas (Galois connections, closure operators)
instead of manual antisymmetry proofs.

- **zeroLocus_vanishingIdeal_eq_closure** (PR #6045): Manual antisymmetry with
  case-by-case reasoning → unified Galois connection approach (9→7 lines)

## 10. Law of Excluded Middle / Classical Reasoning Patterns
**Instances seen: 1**

Using `em` or other classical reasoning primitives directly instead of manual
case analysis.

- **Prop.fintype** (PR #6795): `Classical.cases (by simp) (by simp)` →
  `by simpa using em` (2→2 lines, same length but cleaner)

---

## Observed False Positive Patterns

These patterns were incorrectly classified as HIGH_VALUE:

### A. Signature change forcing proof rewrite (most common ~30% of FPs)
- **linearOrder** (PR #1319): Signature changed from `Subtype p` to `PUnit`
- **weight_sum** (PR #6139): Added `private`, changed argument structure
- **mapsTo_sUnion** (PR #7236): Changed from implication to iff
- **domCongr** (PR #6057): Type notation changed, argument reordering

### B. API removal forcing manual rewrite
- **Eq.subset** (PR #892): Clean `Eq.subset'` replaced by verbose manual proof
  because the library lemma was removed. The final proof is *worse*.

### C. Notation-only changes
- **monad** (PR #281): `⟨cmd⟩` vs `WriterT.mk $`. Stylistic, not structural.

---

## 11. Wrong Tactic for the Job
**Instances seen: 1**

Using a tactic that doesn't match the proof obligation (e.g., `norm_num` when
there are no numerical computations, `decide` on large types).

- **tag_mem** (PR #16675): Reviewer caught `norm_num` used where no numerical
  reasoning was needed. Replaced with proper `exact`/`simp` (5→6 lines, but
  semantically correct)

---

## Aggregate Statistics (v3 prompt, ~890/1904 PRs)

- **Total HIGH_VALUE pairs: ~1,893**
- Signature changed: 27% (main false positive source)
- Shrinking proofs: 64%
- Same size: 23%
- Growing proofs: 13%
- Pair failure rate: 2.1% (116 failures)

If we conservatively filter out signature-changed pairs: ~1,380 HIGH_VALUE.

Estimated final totals (extrapolating to all 1,904 PRs):
- ~3,500-4,000 HIGH_VALUE pairs
- ~2,500-3,000 after filtering signature changes

*Last updated: v3 prompt, ~890 PRs processed*
*Total HIGH_VALUE pairs inspected: ~45*
*Estimated false positive rate: ~20-25% (down from ~40% in v2)*
*Main remaining issue: signature-changed pairs (27% of HIGH_VALUE)*
