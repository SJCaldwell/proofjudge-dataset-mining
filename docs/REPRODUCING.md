# Reproducing the dataset

Two stages. **Stage 1** mines a corpus of proof pairs from mathlib4 PRs. **Stage 2**
turns that corpus into a held-out eval set whose labels have been individually
verified. Stage 1 is the original pipeline; stage 2 was added after we discovered
that a corpus you can mine is not the same as an eval set you can trust.

Budget roughly: stage 1 is ~$200 of Claude API spend and most of a day of wall
clock, dominated by GitHub rate limits. Stage 2 is a few minutes of compute plus
one Claude Code Workflow run.

---

## Prerequisites

    uv sync
    cp .env.example .env      # then fill in the two keys below

`.env` needs:

- `GITHUB_TOKEN` — a fine-grained PAT with public-repo read. Rate limits are the
  binding constraint on stage 1, not the token's permissions.
- `ANTHROPIC_API_KEY` — for the stage-1 labelling pass.

Stage 2's adjudication runs through Claude Code's Workflow tool, which bills a
Claude subscription rather than API credits. That is the only reason it is a
workflow and not a script.

---

## Stage 1 — mine the corpus

    proofjudge discover        # find candidate PRs (GraphQL scan + keyword search)
    proofjudge enrich          # PR metadata, merge status, review counts
    proofjudge extract         # reviews, comments, commits, changed files
    proofjudge parse           # parse .lean files at both SHAs, match declarations
    proofjudge summarize       # LLM labels each pair HIGH_VALUE / LOW_VALUE / CONTEXTUAL
    proofjudge assemble        # write data/dataset/proofjudge.jsonl
    proofjudge status          # progress at any point

Every phase is resumable — state lives in `data/proofjudge.db`, so an interrupted
run picks up where it stopped. Re-running a completed phase is a no-op.

### Two different filters decide what survives — don't conflate them

This trips people up, so it is worth stating plainly. A pair has to pass **both**:

**1. A mechanical difference threshold** (`pipeline/parsing.py`, no LLM, free).
Declarations are matched by name across the PR's first and last commit, and a
pair is kept only if the proof body actually changed enough to be interesting:

    _MIN_CHANGED_TOKENS    = 3      # bag-of-tokens diff: added + removed
    _MIN_CHANGE_PROPORTION = 0.05   # relative to the *shorter* proof

The proportional test is what stops a 116-line proof with one renamed tactic
from counting as a rewrite. There is also a hardcoded filter for the mechanical
`refine'` → `refine` migration, which is a mass rename rather than a change of
approach.

**2. An LLM quality classification** (`pipeline/summarization.py`, ~$200).
Every surviving pair is shown to Claude — the two proofs, the declaration, a
`signature_changed` flag, and the relevant reviewer comments — and classified:

    HIGH_VALUE   the proof's approach genuinely improved
    LOW_VALUE    trivial, mechanical or cosmetic
    CONTEXTUAL   the change was forced by something outside the proof —
                 a renamed lemma, a refactored definition, a changed statement

Only HIGH_VALUE reaches the dataset. This is a judgement about *quality*, not
about *magnitude*: a large diff that only adapts to a renamed lemma is
CONTEXTUAL, and a small diff that replaces a manual construction with the right
library lemma is HIGH_VALUE.

The prompt lives in `pipeline/prompts.py` and carries five worked examples. If
you retarget this at another library, that prompt is the first thing to rewrite —
its examples are mathlib-specific and it is what defines "quality" for your
whole corpus.

One caveat inherited from this design: the classifier sees the **review
comments**, so a pair can be labelled HIGH_VALUE on the strength of a reviewer's
remark even when the improvement is not visible in the proof text. That is
exactly the gap stage 2's blind adjudication measures, and on same-or-longer
pairs it turned out to be large.

### Things worth knowing before you start

**mathlib4 merges via Bors, not GitHub.** Merged PRs show up as *closed*, with
`merged_at` null and a `[Merged by Bors] - ` title prefix. GitHub's `is:merged`
misses ~29,000 real merges and `is:unmerged` returns them as false positives. The
pipeline detects this by title prefix; if you point it at a different repository,
check that repo's merge mechanics first.

**The GitHub search index undercounts.** `review-comments:>0` reports far fewer
PRs than actually exist. Discovery uses a full GraphQL scan plus keyword searches
rather than trusting search counts.

**`summarize` is where the money goes.** ~$200 for ~11k pairs. Start with
`--limit 50` to sanity-check the prompt against your corpus before committing.

---

## Stage 2 — build a verified eval set

    proofjudge evalset select --against <reference>.jsonl
    proofjudge evalset audit
    proofjudge evalset emit-tasks --reference <reference>.jsonl
    # ... run the adjudication workflow (below) ...
    proofjudge evalset verify

`--against` is an existing eval set the new one must not overlap — pass your dev
or calibration split. Omit it for a first set. Artifacts land in `data/evalset/`.

### select

Draws a stratified set and prints a rejection funnel showing what each filter
removed. Two strata: `api_design`-tagged pairs and everything else, sized to put
`api_design` near its corpus rate rather than letting a stratum artifact set it.

Every exclusion in `select.py` exists because it caused a measured problem, and
each is commented with which one. The two most important:

- **Same-or-longer pairs are excluded.** Blind readers supported the label on
  only 43.3% of them, against 89–93% for shrinking pairs. Such changes are
  near-identical textually, near-identical changes are frequently lateral, and
  the label survived only because the annotator read review comments that the
  proof text does not contain. They are not labelable from proofs alone.
- **`signature_changed` pairs are excluded.** They invert at 38.5% against 10.9%
  for the rest. When the statement changes, the initial proof's shape is forced
  rather than chosen, so it is not a clean test of judgement.

### audit

Mechanical defect checks — no LLM, no cost. Run it before spending adjudication
budget; there is no point judging rows you already know to drop. On a set drawn by
`select` it should report zero findings, because the same filters run at selection
time. It earns its keep on sets built any other way.

### emit-tasks

Writes three files:

- `<prefix>_tasks.jsonl` — what the adjudicator sees. Exactly five fields:
  `task_id`, `declaration`, `file_path`, `proof_a`, `proof_b`.
- `<prefix>_key.json` — which slot held the accepted proof. **The adjudicator
  never sees this.**
- `<prefix>_batches.json` — agent assignments.

Blinding is enforced by the data, not by prompt instruction. There is no
`initial_proof`/`final_proof` field name, no `rejection_reasons`, no line counts,
no category tags — an adjudicator cannot infer the answer from a field name
because the field names carry none. `emit` raises if a provenance field would
leak.

Also note what is *absent*: the replicate number. Replicate 0 always puts the
accepted proof in slot A, so exposing `rep` would leak the answer outright.

**Order balancing.** Each pair is judged three times: replicate 0 with the
accepted proof as A, replicate 1 with it as B, replicate 2 by a stable hash. Every
pair is seen both ways, which turns position bias from a nuisance you average away
into a number you report. Agents are partitioned by replicate so no agent ever
sees the same pair twice.

### Running the adjudication

    Workflow({
      scriptPath: "workflows/blind_adjudication.js",
      args: { dir: "<abs path>/data/evalset", nBatches: <from emit-tasks>, prefix: "blind" }
    })

`nBatches` must equal the batch count `emit-tasks` printed. If a batch fails —
usually a transient classifier error — resume rather than re-running:

    Workflow({ scriptPath: "workflows/blind_adjudication.js",
               resumeFromRunId: "<run id>", args: {...} })

Completed agents replay from cache; only the failed batch re-runs.

**Check the anchors before you run.** `data/evalset/anchors.md` shows the
adjudicator four labelled examples: two clear improvements, one subtle, and one
genuinely *comparable*. That mix is load-bearing. An earlier version used three
anchors that all resolved "the second is better", which taught the adjudicator to
go find an improvement and biased it against the `comparable` verdict — the exact
verdict the study exists to measure. If you swap in your own anchors, keep a
comparable one, and make sure it has real code differences: a comment-only diff
teaches "comparable means byte-identical", which is worse than no anchor.

### verify

Decodes verdicts, reports label support with a confidence interval, and writes
`verified_rows.jsonl` with the failures removed.

Read three things before trusting the output:

- **Position bias.** Should be ~0.500. Ours came in at 0.515 / 0.495 / 0.504
  across three runs. A real deviation means the adjudicator is preferring a
  *slot*, which invalidates every verdict.
- **Replicate unanimity.** How often all three replicates agree. Low unanimity
  means soft labels, independent of which way they went.
- **Failures by type.** Unanimous-initial-better, unanimous-comparable, and
  majority-against are different findings. A unanimous "comparable" is a label
  that is not wrong so much as not there.

If the per-agent verdict files are gone but the workflow ran, recover from the
journal:

    proofjudge evalset verify --journal ~/.claude/projects/<project>/<session>/subagents/workflows/<run>/journal.jsonl

---

## What this does not establish

The adjudicator is an LLM checking a dataset an LLM labelled. Using a different
model family than the labeller (we labelled with Sonnet and adjudicated with Opus)
removes the most obvious circularity but not all of it. What the verification
establishes is that **a capable reader, shown only the two proofs, independently
agrees with the label** — not ground truth.

The label itself is Mathlib's revision history, not a human ranking. The "final"
proof is the version Mathlib merged; the "initial" is the same declaration when
the PR opened. No reviewer was ever asked which is better, and an author may have
revised for reasons unrelated to proof quality. That gap is precisely what blind
adjudication measures, and on same-or-longer pairs it turned out to be large.
