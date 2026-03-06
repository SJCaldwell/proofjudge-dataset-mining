# ProofJudge: Project Plan for AITP 2026

## Venue Assessment

**Primary target: AITP 2026** (Aussois, France, August 30 – September 4, 2026)

AITP 2025 required a **2-page extended abstract** (excluding references) with a deadline of May 5 (extended to May 12). The 2026 CFP hasn't dropped yet, but the deadline will almost certainly land in early-to-mid May 2026 — roughly 60 days from now.

This is the right first venue for several reasons:

- The audience is precisely the AI + theorem proving intersection. Sean Welleck, Josef Urban, Mario Carneiro, and other Lean/Mathlib-adjacent researchers attend regularly.
- A 2-page extended abstract is a low-stakes format: you need a clear problem statement, a preliminary rubric, and initial results — not a complete system evaluation.
- AITP is a discussion-oriented conference (week-long retreat in the French Alps). Getting feedback here directly informs the fuller paper.
- The submission format is non-archival, so you can submit the full ProofJudge paper to a peer-reviewed venue afterward without conflict.

**Secondary targets (for the full paper, later):**

| Venue | Format | Likely Deadline | Notes |
|---|---|---|---|
| CPP 2027 | Full paper (16pp) | ~Sep 2026 | Co-located with POPL. Formal verification audience. |
| CICM 2026 | Full paper | ~Jun 2026 | Where "Growing Mathlib" appeared. Good fit for tooling angle. |
| NeurIPS 2026 workshop | Extended abstract | ~Aug 2026 | For the general "Verification-Grounded LLM-as-Judge" framing. |
| ICLR 2027 | Full paper | ~Oct 2026 | Main track if the framework paper is strong enough. |

---

## Timeline: 60 Days to AITP Submission (~May 5, 2026)

### Phase 1: Lean Foundations (Weeks 1–3, Mar 4 – Mar 24)

**Goal:** Enough fluency to speak credibly about proof style and to understand Mathlib norms.

- Work through Heather Macbeth's *The Mechanics of Proof* text (math2001). This is the text you've already identified. Focus on the first 6–8 chapters. Keep a log of decision points where you chose between equivalent approaches (tactic vs. term, `simp` vs. explicit rewrite, etc.).
- Set up a Lean 4 / Mathlib dev environment. Get `lake` working, pull Mathlib, build it, and browse the source.
- Read the Mathlib style guide and contributor docs. Pay particular attention to the linter descriptions (the `Mathlib.Tactic.Linter.Style` and `FlexibleLinter` modules) — these are the *codified* norms your rubric will need to go beyond.
- Read the "Growing Mathlib" paper (Rothgang et al., CICM 2025, arXiv:2508.21593). This is your immediate predecessor work on the tooling side.
- Read the "Maintaining a Library of Formal Mathematics" paper (van Doorn, Ebner, Lewis, CICM 2020). Covers the linter design philosophy.

**Deliverable:** A working Lean environment and a personal log of style observations from working through the text.

### Phase 2: PR Mining & Rubric Draft (Weeks 3–5, Mar 24 – Apr 7)

**Goal:** Extract evaluation data from Mathlib PR history and draft an initial rubric.

- Write scripts to mine Mathlib PR history via GitHub API. Target PRs that:
  - Were merged after revision (at least one review round with requested changes).
  - Have reviewer comments that reference style, structure, or idiom — not just mathematical correctness.
  - Ideally touch proof code rather than infrastructure/CI.
- Categorize reviewer feedback into clusters. Expected categories include:
  - Tactic hygiene (non-terminal `simp`, `decide` misuse, tactic golf)
  - Generality of definitions and lemma statements
  - Proof structure and readability (mirroring informal argument vs. brute-force automation)
  - Naming conventions and API design
  - `simp` lemma direction and normal forms
  - Module organization and import discipline
- Draft a hierarchical rubric following the PentestJudge pattern: top-level categories → subcategories → binary leaf criteria. Each leaf should be a yes/no question a judge can answer by examining the proof.
- Identify 15–25 PR pairs (initial submission, accepted revision) as your evaluation set.

**Deliverable:** A draft rubric (tree structure) and a curated evaluation dataset of PR pairs with reviewer commentary.

### Phase 3: Zulip Engagement (Week 5, Apr 7 – Apr 14)

**Goal:** Get community feedback on the rubric before committing to the AITP submission.

- Post a proposal on the Lean Zulip (probably the `#mathlib4` or `#general` stream). Structure it as:
  1. Motivation: reviewer bottleneck, LLM-generated proofs increasing the need for quality assessment beyond compilation.
  2. The rubric draft. Ask: "What's missing? What's wrong? What criteria do you actually care about in review?"
  3. The deployment vision: a GH Action that scores PRs on style dimensions before human review.
  4. Explicit ask: would 2–3 reviewers be willing to validate the rubric against a sample of their past reviews?
- Incorporate feedback into the rubric. Even a few responses sharpen the criteria substantially.
- If you get buy-in from a maintainer or active reviewer, that's a potential co-author or acknowledged collaborator for the paper.

**Deliverable:** A community-validated rubric (or at least community-informed). Potential collaborators identified.

### Phase 4: Preliminary Experiments (Weeks 5–7, Apr 7 – Apr 21)

**Goal:** Run the judge on enough examples to have preliminary results for the abstract.

- Implement the ProofJudge system. This is structurally identical to PentestJudge: an LLM (Claude or GPT-4) with a system prompt containing the rubric, given a proof (or PR diff) as input, asked to evaluate each leaf criterion.
- Run the judge on your 15–25 PR pairs. For each pair:
  - Score the initial (pre-revision) proof.
  - Score the accepted (post-revision) proof.
  - Check whether the accepted version scores higher on the dimensions the reviewer flagged.
- Compute agreement metrics: what fraction of the time does the judge's ranking match the reviewer's preference? Break this down by rubric category.
- Characterize failure modes. Where does the judge disagree with reviewers? Is it because the rubric is underspecified, or because the judge misunderstands the proof?

**Deliverable:** A table of preliminary results showing judge-reviewer agreement rates, broken down by rubric category.

### Phase 5: Write the Abstract (Weeks 7–8, Apr 21 – May 3)

**Goal:** A 2-page extended abstract ready for AITP submission.

The abstract should contain:

1. **Problem statement** (1 paragraph): Formal proofs can be correct but vary widely in quality. Existing linters catch surface-level issues but can't assess deeper structural and stylistic properties. As LLMs generate more proofs, the need for automated quality assessment beyond compilation grows.

2. **Approach** (1 paragraph): ProofJudge is an LLM-as-judge system with a hierarchical rubric grounded in Mathlib's review norms. The rubric uses binary leaf criteria organized into categories (tactic hygiene, generality, structure, naming). The Lean kernel provides objective correctness anchoring; the judge evaluates softer quality dimensions on top.

3. **Rubric design** (1/2 page): Show the rubric tree. Describe how it was derived from PR review mining and community feedback. Highlight the tension between what linters can check and what requires judgment.

4. **Preliminary results** (1/2 page): PR pair evaluation. Agreement rates. Key failure modes.

5. **Framing** (1 paragraph): Connect to the broader "Verification-Grounded LLM-as-Judge" research program. Note PentestJudge as the first instance of the pattern. Position ProofJudge as the second, in a domain different enough to test generality.

6. **References**: PentestJudge, Growing Mathlib, Maintaining a Library of Formal Mathematics, relevant autoformalization work.

**Deliverable:** Submitted 2-page abstract.

---

## Risk Assessment

**Lean learning curve too steep in 3 weeks.** Mitigation: You don't need deep Lean expertise for the AITP abstract. You need enough to understand what the rubric criteria mean and to read PR diffs. The Macbeth text plus browsing Mathlib PRs should be sufficient. Deeper fluency matters more for the full paper.

**PR mining yields insufficient data.** Mitigation: Mathlib has thousands of merged PRs with review comments. Even a rough keyword filter (e.g., reviewer comments containing "simp", "generalize", "style", "readability", "idiomatic") should surface enough candidates. Start with recent PRs where the review norms are most current.

**Zulip engagement is lukewarm.** Mitigation: The abstract can proceed without community co-design — you just frame the rubric as "derived from published norms and PR review analysis" rather than "community-validated." But a good Zulip post costs almost nothing and the upside is high.

**Judge agreement is low.** Mitigation: For a 2-page AITP abstract, honest preliminary results with analysis of *why* the judge fails are more valuable than inflated numbers. The community will respect a clear problem characterization even with modest initial performance.

---

## Connection to Larger Research Arc

The AITP abstract plants the flag. The sequence from here:

1. **AITP 2026** (Aug): Present ProofJudge, get feedback from the AI+TP community.
2. **Full ProofJudge paper** (target CPP 2027 or CICM 2026): Complete evaluation, larger dataset, community-validated rubric, deployment as GH Action.
3. **Framework paper** ("Verification-Grounded LLM-as-Judge"): PentestJudge + ProofJudge as case studies. Target NeurIPS/ICLR workshop first, then main track if the empirical story is strong.
