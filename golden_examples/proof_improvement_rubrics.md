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
**Instances seen: 5**

The initial proof manually sequences rewrite steps that `simp`/`simp_all`/`omega`/
`grind` can find automatically with the right lemma hints.

- **sum_range_multichoose** (PR #33656): 10→5 lines, manual `conv_lhs`/`rw` chain
  replaced by `simp_all [Finset.sum_range_succ', fib_add_two]`
- **isEdgeReachable_one** (PR #32870): 11→2 lines, manual constructor replaced
  by `simp` with right lemmas
- **range_ite_subset'** (PR #27287): Manual `by_cases` + `if_pos`/`if_neg` rewrites
  + explicit subset lemmas → single `grind` call
- **card_sdiff_add_card_eq_card** (PR #29427): Manual `Nat.sub_eq_iff_eq_add` chain
  with `.mp`/`.symm` → single `grind` call
- **append_assoc** (PR #30960): Manual induction with explicit `cons_append` rewrites
  → `induction p <;> simp [*]`

## 5. Term Mode Over Unnecessary Tactic Mode
**Instances seen: 2**

When the proof is a direct application or composition, tactic mode
(`by apply/exact`) adds unnecessary overhead.

- **cellFrontier_subset_complex** (PR #20287): `apply subset_trans` →
  `.trans` dot notation (3→3 lines, but cleaner)
- **condIndepFun_self_left** (PR #29554): Tactic-mode `refine` + `rw` → direct
  term-mode application with `comap_measurable Z`

## 6. Choosing Better Tactic Variants
**Instances seen: 4**

Using a more appropriate tactic variant that handles the goal more directly.

- **measure_eq_measure_preimage** (PR #7795): Manual `eq_or_lt_of_le` case
  analysis replaced by `inter_distrib_left`, `preimage_union` set operations
  (50→44 lines)
- **sigmoid_mul_rexp_neg** (PR #30653): `field_simp` + `ring` → single `field`
  tactic (4→3 lines)
- **zeta_limit_aux1** (PR #30653): `field_simp [...]; ring_nf` → single `field`
  tactic
- **exists_lub_Iio** (PR #30073): `by_cases` + `by_contra` + `push_neg` chain →
  `by_cases!` which handles negation automatically

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

## 12. Extracting Helper Lemmas for Decomposition
**Instances seen: 3**

A long proof with inline `have` statements or repeated reasoning should be
decomposed into helper lemmas, making both the main theorem and intermediates
reusable and readable.

- **integral_log** (PR #20682): 44-line inline case analysis → 5-line proof
  using extracted `integral_log_from_zero` helpers. Reviewer: "Can you extract
  this `have` into its own lemma?"
- **intervalIntegrable_of_even** (PR #20682): Inline `have` for 0-based
  integrability → extracted `intervalIntegrable_of_even₀` helper
- **logMahlerMeasure_X_sub_C** (PR #30548): 73→36 lines by extracting
  `divisor_sub_const_self` and `divisor_sub_const_of_ne` lemmas

## 13. Unnecessary Hypothesis Removal
**Instances seen: 2**

The theorem statement carries a hypothesis that isn't actually needed,
which a judge should recognize as a generality improvement.

- **Tape.write_mk'** (PR #30821): Removed unnecessary parameter `a` from
  theorem statement, making it more broadly applicable
- **zpow_neg** (PR #28090): Removed `x_ne_zero` and `x_ne_top` hypotheses
  by handling edge cases directly in the proof (1→8 lines, but unconditional)

## 11. Wrong Tactic for the Job
**Instances seen: 1**

Using a tactic that doesn't match the proof obligation (e.g., `norm_num` when
there are no numerical computations, `decide` on large types).

- **tag_mem** (PR #16675): Reviewer caught `norm_num` used where no numerical
  reasoning was needed. Replaced with proper `exact`/`simp` (5→6 lines, but
  semantically correct)

---

## Aggregate Statistics (v3 prompt, FINAL — 1904/1904 PRs)

- **Total pairs classified: 10,676**
- **HIGH_VALUE: 4,215 (39.5%)**
- **LOW_VALUE: 2,975 (27.9%)**
- **CONTEXTUAL: 3,486 (32.7%)**
- **Pair failure rate: 0%**
- With explicit review feedback: 62.4% of HIGH_VALUE
- Signature changed: 23.4% of dataset rows (982/4196)

**Final dataset: 4,196 rows** from 1,038 PRs across 1,377 unique files.

Category distribution (HIGH_VALUE only):
- proof_structure: 3,867 (92%)
- tactic_hygiene: 3,661 (87%)
- readability: 971 (23%)
- api_design: 967 (23%)
- generality: 457 (11%)
- simp_lemmas: 413 (10%)
- performance: 114 (3%)

Proof size changes:
- Shrinking: 66.7%, Same: 22.6%, Growing: 10.7%
- Average delta: -3.2 lines
- Median initial: 6 lines, Median final: 4 lines

Cost: ~$214 (55M input + 3.2M output tokens via Claude Sonnet)

*Last updated: v3 prompt, COMPLETE*
*Total HIGH_VALUE pairs inspected: ~75*
*Estimated false positive rate: ~15-20%*
*Main remaining issue: api_design-tagged pairs without review feedback*
