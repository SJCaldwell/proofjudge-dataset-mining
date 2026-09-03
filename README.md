# ProofJudge — dataset mining

Mines proof-quality pairs from [mathlib4](https://github.com/leanprover-community/mathlib4)
pull requests: the state a declaration was in when a PR opened, and the state
Mathlib merged. Used to evaluate whether an LLM judge can tell which is better.

Companion harness (runs judges against these sets):
https://github.com/SJCaldwell/ProofJudge

## Layout

    src/proofjudge/
      pipeline/     stage 1 — mine a corpus of proof pairs from PRs
      evalset/      stage 2 — turn that corpus into a verified eval set
      lean/         Lean 4 declaration parser
      github/       GraphQL + REST clients, rate limiting, retries
      models/       pydantic schemas
    workflows/      Claude Code Workflow scripts (blind adjudication)
    docs/           REPRODUCING.md — start here
    data/           all outputs (gitignored)

## Quick start

    uv sync
    cp .env.example .env    # GITHUB_TOKEN + ANTHROPIC_API_KEY
    proofjudge --help

Then follow [docs/REPRODUCING.md](docs/REPRODUCING.md), which walks both stages
end to end and flags the traps that cost us time.

## Why there are two stages

Stage 1 produces a large corpus cheaply. Stage 2 exists because we learned the
hard way that those are different artifacts:

- **A corpus you can mine is not an eval set you can trust.** Selecting rows on
  metadata alone — length ratios, category tags, a quality flag — produced a set
  where blind readers could not confirm the label on 27% of rows. The same
  protocol on a hand-curated set failed on 3%.
- **The failures concentrate.** One stratum (proofs that did not get shorter)
  accounted for almost all of it, at 43% label support against 89–93% elsewhere.
  Those changes are near-identical textually, and near-identical changes are
  frequently lateral rather than improvements.
- **Some rows were not proofs at all.** Linters, CLI tools and tactic
  implementations leaked in through a path-filter bug and scored very differently
  from mathematics (31.6% aligned, 52.6% inverted, against 60.6%/24.7%).

Stage 2 filters all three at selection time and then verifies what survives by
blind adjudication. See `src/proofjudge/evalset/select.py` — every exclusion is
commented with the measurement that motivated it.

## Known limitations

- **Only merged PRs are sampled.** `qualifies_for_extraction` requires a merge,
  so submissions rejected outright never enter the corpus. One consequence: the
  corpus is 100% human-authored, and cannot be used to study AI-generated proof
  detection — machine-written submissions are the ones closed unmerged.
- **Labels come from an LLM pass** over the diff plus review comments, so they
  encode that model's judgement, not a reviewer's. Blind adjudication in stage 2
  checks them but cannot establish ground truth.
- **`data/` is gitignored.** Corpus and eval artifacts are reproducible from the
  pipeline, not committed. Published sets live on HuggingFace.
