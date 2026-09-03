# Reproducing the dataset

There are two stages. Stage 1 mines a corpus of proof pairs from mathlib4 PRs.
Stage 2 takes that corpus and builds a held-out eval set from it, with every
label checked. Stage 1 is the original pipeline. Stage 2 came later, once it was
clear that a big corpus and a trustworthy eval set aren't the same thing.

Rough budget: stage 1 is about $200 of Claude API spend and most of a day of
wall-clock time, nearly all of it waiting on GitHub rate limits. Stage 2 is a
few minutes of local compute plus one Claude Code Workflow run, which takes
about twenty minutes.

---

## Prerequisites

    uv sync
    cp .env.example .env      # then fill in the two keys

`.env` needs:

- `GITHUB_TOKEN`: a fine-grained PAT with read access to public repos.
  Permissions aren't the issue; rate limits are what slow stage 1 down.
- `ANTHROPIC_API_KEY`: used by the stage-1 labelling pass.

Stage 2's adjudication runs through Claude Code's Workflow tool, which bills
against a Claude subscription instead of API credits. That's the only reason
it's a workflow rather than a script.

---

## Stage 1: mine the corpus

    proofjudge discover        # find candidate PRs (GraphQL scan + keyword search)
    proofjudge enrich          # PR metadata, merge status, review counts
    proofjudge extract         # reviews, comments, commits, changed files
    proofjudge parse           # parse .lean files at both SHAs, match declarations
    proofjudge summarize       # LLM labels each pair HIGH_VALUE / LOW_VALUE / CONTEXTUAL
    proofjudge assemble        # write data/dataset/proofjudge.jsonl
    proofjudge status          # progress at any point

Every phase is resumable. State lives in `data/proofjudge.db`, so an interrupted
run picks up where it left off, and re-running a finished phase does nothing.

### Two filters decide what survives

It's easy to conflate these, so here they are side by side. A pair has to pass
both.

**The mechanical difference threshold** (`pipeline/parsing.py`; no LLM
involved). Declarations are matched by name between the PR's first and last
commit. A pair is kept only if the proof body changed by enough to be
interesting:

    _MIN_CHANGED_TOKENS    = 3      # bag-of-tokens diff: added + removed
    _MIN_CHANGE_PROPORTION = 0.05   # relative to the shorter proof

The proportional test is what keeps a 116-line proof with one renamed tactic
from counting as a rewrite. There's also a hardcoded filter for the `refine'` to
`refine` migration, which was a mass rename rather than a change in approach.

**The LLM quality classification** (`pipeline/summarization.py`; this is where
the ~$200 goes). Each surviving pair is sent to Claude with the two proofs, the
declaration, a `signature_changed` flag and the relevant reviewer comments, and
comes back as one of:

    HIGH_VALUE   the approach to the proof improved
    LOW_VALUE    trivial, mechanical or cosmetic
    CONTEXTUAL   the change was forced from outside the proof:
                 a renamed lemma, a refactored definition, a changed statement

Only HIGH_VALUE makes it into the dataset. This is a call about quality, not
size. A large diff that only adapts to a renamed lemma is CONTEXTUAL; a small
one that swaps a manual construction for the right library lemma is HIGH_VALUE.

The prompt is in `pipeline/prompts.py` with five worked examples. If you point
this at a different library, rewrite that prompt first. The examples are
mathlib-specific, and the prompt is what defines "quality" for the whole
corpus.

One consequence of this design to keep in mind: the classifier sees the review
comments, so a pair can be labelled HIGH_VALUE because a reviewer said
something, even when the improvement isn't visible in the proof text. Stage 2's
blind adjudication measures that gap, and on pairs where the proof didn't get
shorter it turned out to be wide.

### The reference dataset

You don't need to rebuild ours to compare against it. It's public and needs no
token:

    https://huggingface.co/datasets/SJCaldwell/proofjudge

    curl -sL -o test_eval.jsonl \
      https://huggingface.co/datasets/SJCaldwell/proofjudge/resolve/v0.2.0/test/eval.jsonl

`v0.1.0` is the 123-declaration `dev` split. `v0.2.0` adds the 218-declaration
`test` split. The judge harness downloads these on first run, so you only need
the URL if you want to inspect or diff them yourself.

One thing to watch when comparing numbers. The dataset card reports
code-similarity over the comment-stripped whole declaration, while
`evalset/lean_text.py` computes it over the body only. The signature is
identical on every pair we keep, so including it pushes the number up. Both are
reasonable; they just aren't the same:

    split   whole-declaration   body-only
    dev            0.391          0.256
    test           0.590          0.477

Say which one you're using. A median of 0.59 that quietly becomes 0.48 looks
like a regression and isn't one.

### Before you start

mathlib4 merges through Bors, not GitHub. Merged PRs show up as closed, with
`merged_at` null and a `[Merged by Bors] - ` prefix on the title. GitHub's
`is:merged` misses around 29,000 real merges, and `is:unmerged` returns them as
false positives. The pipeline goes by the title prefix. If you point it at
another repository, check how that repo merges first.

GitHub's search index undercounts. `review-comments:>0` reports far fewer PRs
than exist. Discovery does a full GraphQL scan plus keyword searches instead of
trusting search counts.

`summarize` is where the money goes: about $200 for roughly 11k pairs. Run it
with `--limit 50` first to check the prompt against your corpus before
committing to the full pass.

---

## Stage 2: build a verified eval set

    proofjudge evalset select --against <reference>.jsonl
    proofjudge evalset audit
    proofjudge evalset emit-tasks --reference <reference>.jsonl
    # ... run the adjudication workflow (below) ...
    proofjudge evalset verify

`--against` names an existing eval set the new one must not overlap with; pass
your dev or calibration split. Leave it off for a first set. Output goes to
`data/evalset/`.

### select

Draws a stratified set and prints a rejection funnel showing what each filter
removed. There are two strata, `api_design`-tagged pairs and everything else,
sized so `api_design` lands near its rate in the corpus rather than wherever a
stratum artifact would put it.

Every exclusion in `select.py` is there because it caused a measured problem,
and each has a comment saying which. The two that matter most:

- Pairs where the proof didn't get shorter are excluded. Blind readers backed
  the label on only 43.3% of them, against 89–93% for shrinking pairs. These
  changes usually stay textually close to the original, close changes are often
  sideways moves, and the label held up only because the annotator had read
  review comments the proof text doesn't contain. You can't label them from
  the proofs alone.
- Pairs with `signature_changed` are excluded. They invert at 38.5% against
  10.9% for everything else. When the statement changes, the shape of the
  initial proof was forced rather than chosen, so it isn't a fair test of
  judgement.

### audit

Mechanical defect checks, no LLM, no cost. Run it before spending adjudication
budget, since there's no point judging rows you already know you'll drop. On a
set from `select` it should report nothing, because the same filters already
ran. It's useful on sets built any other way.

### emit-tasks

Writes three files:

- `<prefix>_tasks.jsonl`: what the adjudicator sees. Exactly five fields:
  `task_id`, `declaration`, `file_path`, `proof_a`, `proof_b`.
- `<prefix>_key.json`: which slot held the accepted proof. The adjudicator
  never sees this.
- `<prefix>_batches.json`: agent assignments.

Blinding is enforced by the data, not by asking the model nicely. There's no
`initial_proof` or `final_proof` field, no `rejection_reasons`, no line counts,
no category tags. The field names carry no information, so there's nothing to
infer from them. `emit` raises if a provenance field would leak.

The replicate number is also left out on purpose. Replicate 0 always puts the
accepted proof in slot A, so exposing `rep` would give the answer away.

Order balancing: each pair is judged three times. Replicate 0 shows the
accepted proof as A, replicate 1 shows it as B, and replicate 2 picks by a
stable hash. Every pair is seen both ways, so position bias becomes a number
you report instead of noise you average out. Agents are split by replicate so
no agent sees the same pair twice.

### Running the adjudication

    Workflow({
      scriptPath: "workflows/blind_adjudication.js",
      args: { dir: "<abs path>/data/evalset", nBatches: <from emit-tasks>, prefix: "blind" }
    })

`nBatches` has to match the batch count `emit-tasks` printed. If a batch fails,
usually from a transient classifier error, resume instead of re-running:

    Workflow({ scriptPath: "workflows/blind_adjudication.js",
               resumeFromRunId: "<run id>", args: {...} })

Finished agents replay from cache; only the failed batch runs again.

Check the anchors before you run. `data/evalset/anchors.md` gives the
adjudicator four labelled examples: two clear improvements, one subtle one, and
one pair that really is comparable. That mix matters. An earlier version used
three anchors that all resolved to "the second one is better", which trained
the adjudicator to go looking for an improvement and biased it against
`comparable`, the verdict the whole study is trying to measure. If you swap in
your own anchors, keep a comparable one, and make sure it has real code
differences. A comment-only diff teaches "comparable means byte-identical",
which is worse than no anchor at all.

### verify

Decodes the verdicts, reports label support with a confidence interval, and
writes `verified_rows.jsonl` with the failures removed.

Three things to check in the output:

- Position bias. Should be near 0.500. Ours came in at 0.515, 0.495, 0.504 and
  0.509 across four runs. A real deviation means the adjudicator prefers a
  slot, and that invalidates every verdict.
- Replicate unanimity: how often all three replicates agree. Low unanimity
  means soft labels, whichever way they went.
- Failures by type. Unanimous initial-better, unanimous comparable, and
  majority-against are different findings. A unanimous "comparable" isn't a
  wrong label so much as a missing one.

If the per-agent verdict files are gone but the workflow ran, recover from the
journal:

    proofjudge evalset verify --journal ~/.claude/projects/<project>/<session>/subagents/workflows/<run>/journal.jsonl

---

## What this does and doesn't establish

The adjudicator is an LLM checking a dataset an LLM labelled. Using a different
model family for the check (Sonnet labelled, Opus adjudicated) removes the most
obvious circularity, but not all of it. What verification shows is that a
capable reader, given only the two proofs, agrees with the label on its own.
That isn't ground truth.

The label itself is Mathlib's revision history, not a human ranking. The
"final" proof is what Mathlib merged; the "initial" is the same declaration
when the PR was opened. Nobody asked a reviewer which was better, and an author
may have revised for reasons that have nothing to do with proof quality.

One more thing to expect. When we re-ran the whole procedure from a clean
checkout, rows already in the published set passed again 95.7% of the time,
but rows new to the draw passed only 20.5% of the time. The first number is
test-retest reliability, since those rows had already been selected for
passing. The second is the base rate of what's left in the pool. Growing the
set past ~218 means mining new PRs, not drawing deeper from this corpus.
