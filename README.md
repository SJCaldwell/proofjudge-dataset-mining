# ProofJudge dataset mining

[![arXiv](https://img.shields.io/badge/arXiv-2608.20432-b31b1b.svg)](https://arxiv.org/abs/2608.20432)
[![Hugging Face Dataset](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Dataset-yellow)](https://huggingface.co/datasets/SJCaldwell/proofjudge)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The data-mining half of [ProofJudge](https://github.com/SJCaldwell/ProofJudge).
Mines proof-quality pairs from [mathlib4](https://github.com/leanprover-community/mathlib4)
pull requests. Each pair is one declaration as it looked when the PR was opened
and as it looked when Mathlib merged it. The pairs are used to test whether an
LLM judge can tell which version is better.

- **Judge harness and paper:** [SJCaldwell/ProofJudge](https://github.com/SJCaldwell/ProofJudge)
- **Published dataset:** [`SJCaldwell/proofjudge`](https://huggingface.co/datasets/SJCaldwell/proofjudge) on Hugging Face

## Layout

    src/proofjudge/
      pipeline/     stage 1: mine a corpus of proof pairs from PRs
      evalset/      stage 2: turn that corpus into a verified eval set
      lean/         Lean 4 declaration parser
      github/       GraphQL + REST clients, rate limiting, retries
      models/       pydantic schemas
    workflows/      Claude Code Workflow scripts (blind adjudication)
    docs/           REPRODUCING.md, which is the place to start
    data/           all outputs (gitignored)

## Quick start

    uv sync
    cp .env.example .env    # GITHUB_TOKEN + ANTHROPIC_API_KEY
    proofjudge --help

Then follow [docs/REPRODUCING.md](docs/REPRODUCING.md). It walks through both
stages end to end and points out the things that cost us time.

## Why there are two stages

Stage 1 mines a corpus. Stage 2 turns part of that corpus into an eval set with
checked labels. They started out as one thing, and we split them after finding
that a corpus we could mine cheaply was not a set we could trust:

- Picking eval rows by metadata alone (length ratios, category tags, the
  quality flag) gave a set where blind readers couldn't confirm the label on 27%
  of rows. The same check on a hand-picked set failed on 3%.
- Nearly all of that came from one stratum: proofs that didn't get shorter.
  Label support there was 43%, against 89–93% everywhere else. Those changes
  tend to stay textually close to the original, and a change that stays close is
  often a sideways move rather than an improvement.
- Some rows weren't proofs. Linters, CLI tools and tactic implementations got in
  through a path-filter bug, and a proof-quality rubric scores them badly (31.6%
  aligned, 52.6% inverted, versus 60.6% and 24.7% for actual mathematics).

Stage 2 applies all three exclusions when it selects rows, then checks the
survivors by blind adjudication. The exclusions live in
`src/proofjudge/evalset/select.py`, each with a comment saying which measurement
led to it. The path-filter bug itself is fixed in `pipeline/parsing.py` as of
`0987e59`.

## Known limitations

- Only merged PRs are sampled. `qualifies_for_extraction` requires a merge, so
  anything rejected outright never enters the corpus. That also means the corpus
  is entirely human-authored and can't be used to study detection of AI-written
  proofs, since those are the submissions that get closed without merging.
- Labels come from an LLM reading the diff and the review comments. They
  reflect that model's judgement, not a reviewer's. Stage 2 checks them but
  can't turn them into ground truth.
- `data/` is gitignored. The corpus and eval artifacts are rebuilt from the
  pipeline rather than committed. The published sets are on HuggingFace.

## Citation

If you use this pipeline or the dataset in your work, please cite:

```bibtex
@misc{caldwell2026proofjudgetoolgroundedllmevaluation,
      title={ProofJudge: Tool-Grounded LLM Evaluation of Formal Proof Quality in Mathlib},
      author={Shane Caldwell},
      year={2026},
      eprint={2608.20432},
      archivePrefix={arXiv},
      primaryClass={cs.LO},
      url={https://arxiv.org/abs/2608.20432},
}
```

## License

MIT. See [LICENSE](LICENSE).
