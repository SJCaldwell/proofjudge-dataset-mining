# ProofJudge Dataset

Proof-quality data mined from [mathlib4](https://github.com/leanprover-community/mathlib4) pull requests. Each entry records how a proof changed during review, from the initial submission to the merged version, along with structured metadata describing what changed and why.

## Directory layout

```
data/
├── dataset/
│   ├── proofjudge.jsonl               (9.4MB, 4,196 rows, full dataset)
│   ├── proofjudge_eval.jsonl          (264KB, 100 rows, declaration-level eval split)
│   ├── proofjudge_eval_pr_level.jsonl (392KB, 100 rows, PR-level eval split)
│   ├── proofjudge_train.jsonl         (9.8MB, 4,096 rows, training split)
│   └── dataset_info.json
├── evalset/                            (stage 2 output: candidates, blind tasks, verdicts)
├── contexts/                           (one file per PR with extracted context)
│   └── pr_{N}.json
├── extraction/                         (318MB, 1,904 files)
│   └── pr_{N}.json
├── parsing/                            (33MB)
│   └── pr_{N}.json
├── summarization/                      (18MB)
│   └── pr_{N}.json
└── proofjudge.db                       (SQLite pipeline state)
```

## The held-out eval set (`v0.3-verified`, 218 rows)

A larger held-out set built from the same corpus. It's meant to sit alongside the 123-declaration set, not replace it. 218 rows, one declaration per PR, 218 distinct PRs, and every row was individually checked by blind adjudication. It's published as the `test` split of [`SJCaldwell/proofjudge`](https://huggingface.co/datasets/SJCaldwell/proofjudge) at tag `v0.2.0`.

### How rows were selected

A row had to have the HIGH_VALUE label; `signature_changed` false; an initial proof of at least 5 lines; explicit reviewer feedback; a non-empty `rejection_reasons`; initial and final proofs that still differ after stripping comments; and a path outside mathlib's infrastructure and tooling directories. It also had to have no PR overlap and no declaration-plus-file overlap with the 123-row set. One row per PR, drawn round-robin across years.

Two strata: B is api_design-tagged shrinking proofs (59 rows), C is everything else that shrinks (159 rows). api_design ends up at 27.1%, compared with 23.0% in the corpus and 12.2% in the 123-row set.

### What's left out, and why

Proofs that didn't get shorter are excluded entirely. An earlier version of this set had a 100-row stratum of them. Blind adjudication put label support in that stratum at 43.3%, against 93.3% and 89.2% for the two strata that were kept. Those changes usually stay textually close to the original, and close changes are often sideways moves. The HIGH_VALUE label held up on them only because the labelling model had read review comments the proof text doesn't contain. Since they can't be labelled from the proofs alone, they were dropped.

`generality` is under-represented, at 0.101 per row against 0.293 in the 123-row set. This is a known gap rather than an accident. Generality shows up in big shrinking rewrites, and weighting toward those would mean weighting toward low-similarity, easy rows that cover the same ground as the development set. A held-out set that repeats the dev set's easy region is less useful than one that covers new ground.

`api_design` sits at 27.1% and not higher because the eligible pool is small: 128 rows across 101 PRs after filtering.

### Label verification, and its limits

Every row was blind-adjudicated. A model saw the two proofs as "Proof A" and "Proof B", with the declaration name and nothing else: no `rejection_reasons`, no line counts, no category tags, and nothing to say which version Mathlib accepted. Each pair was judged three times in balanced order (replicate 0 shows the accepted proof as A, replicate 1 as B, replicate 2 by a stable hash). The blinding comes from the task file's schema rather than from prompt instructions; the fields just don't contain provenance.

Of 237 candidate rows, 218 were confirmed, meaning the accepted version was judged the better proof. 19 were removed: 1 where all three replicates preferred the pre-review proof, 10 where all three called the pair comparable, and 8 where the majority went against the label. There were no three-way splits. All 19 came from stratum C; stratum B was confirmed 59 out of 59.

Position bias across the three runs was 0.515, 0.495 and 0.504 against a null of 0.500. Replicate unanimity was 91.2% on the final batch.

The adjudicator was `claude-opus-5`, chosen so it wouldn't be the `claude-sonnet-4-20250514` that produced the labels. This is still an LLM checking an LLM-built dataset, and it can't establish ground truth. What it establishes is that a capable reader shown only the proofs independently agrees with the label on every surviving row.

Re-running the full procedure from repo code in September 2026 reproduced 211 of the 218 rows at the candidate stage and re-confirmed 202 of them. Rows new to that draw passed at only 20.5%, so this set is close to what the corpus can supply under these filters.

### Expected difficulty

This set is harder than the 123-row set by construction. Median code-similarity between initial and final (body only, comments stripped) is 0.477 against 0.256, and 53 rows sit above 0.75 similarity against 8. Dropping the same-or-longer stratum removed rows that couldn't be labelled, not rows that were hard. A judge scoring in the low 70s here, where it scores around 80% on the 123-row set, is the set working as designed.

The dataset card on HuggingFace reports similarity over the whole declaration rather than the body, which gives 0.590 and 0.391 for the same two sets. Both are correct; they're different measures.

## Infrastructure paths in the corpus (fixed in code, still in the shipped file)

`INFRA_PATH_PREFIXES` (`models/pr.py`) was originally applied only in `is_proof_touching`, a PR-level check asking whether the PR touched at least one non-infrastructure `.lean` file. `parse_single_pr` then parsed every `.lean` file in the PR with no filter of its own, so a PR touching both `Mathlib/Algebra/Foo.lean` and `scripts/lint-style.lean` contributed declarations from both. `Cache/`, `LongestPole/`, `Mathlib/Tactic/`, `Mathlib/Util/` and `*/Linter/` weren't in the prefix list at all.

The result is that 97 of the 4,196 rows in `proofjudge.jsonl` (2.3%) are not mathematical proofs: linters, CLI tools, tactic implementations, elaborator code (monadic `do` blocks over `CommandElabM`, `MetaM`, `IO`). A proof-quality rubric handles these badly. In one measured run they aligned at 31.6% and inverted at 52.6%, against 60.6% and 24.7% for the rest of the same set.

As of commit `0987e59` the filter also runs in `parse_single_pr`, and the prefix list covers the directories above. The shipped `proofjudge.jsonl` predates that fix and still contains the 97 rows; re-running `proofjudge parse` and `assemble` will exclude them. The eval cuts in `data/evalset/` filter these paths at selection time regardless, so a cut can be clean even when the corpus file isn't.

## Eval Dataset: `proofjudge_eval_pr_level.jsonl`

100 rows, one per PR. This is the primary eval file for judging proof quality at the PR level.

### Schema

| Field | Type | Description |
|-------|------|-------------|
| `pr_number` | int | PR number |
| `pr_url` | str | GitHub URL |
| `pr_title` | str | PR title; conveys intent (`feat:`, `chore:`, `refactor:`, etc.) |
| `pr_author` | str | PR author login |
| `reviewers` | list[str] | Reviewer logins |
| `created_at` / `closed_at` | str | ISO timestamps |
| `review_duration_days` | float | Days from creation to merge |
| `file_paths` | list[str] | Deduplicated paths of files with changed declarations |
| `declaration_count` | int | Number of changed proofs (1 for 77 PRs, 2+ for 23 PRs) |
| `declarations` | list[object] | Per-declaration detail (see below) |
| `feedback_categories` | list[str] | Merged categories across all declarations |
| `total_initial_line_count` | int | Sum of initial proof lines across declarations |
| `total_final_line_count` | int | Sum of final proof lines across declarations |
| `total_line_count_delta` | int | Net line change |
| `dataset_version` | str | Version tag |
| `extraction_date` | str | Date the data was extracted |

### `declarations[i]` fields

| Field | Type | Description |
|-------|------|-------------|
| `declaration_name` | str | e.g., `isEdgeReachable_one` |
| `declaration_kind` | str | `theorem`, `lemma`, `def`, or `instance` |
| `file_path` | str | File containing this declaration |
| `initial_proof` | str | Full proof text (signature + body) at first commit |
| `final_proof` | str | Full proof text at last commit (the accepted version) |
| `rejection_reasons` | str | LLM-generated summary of what changed and why |
| `feedback_categories` | list[str] | Categories for this declaration |
| `key_changes` | list[str] | Bullet points describing specific changes |
| `initial_line_count` | int | Line count of initial proof |
| `final_line_count` | int | Line count of final proof |
| `line_count_delta` | int | Line count change |
| `signature_changed` | bool | Whether the type signature changed (not just the proof body) |

### Feedback categories

- `tactic_hygiene`: Use of appropriate tactics, avoiding deprecated or verbose ones
- `proof_structure`: Overall proof organization, mode choice (tactic vs term)
- `readability`: Clarity, naming within proofs, formatting
- `generality`: Removing unnecessary hypotheses, generalizing results
- `naming`: Declaration naming conventions
- `performance`: Tactic execution speed (e.g., `grind` vs `simp`)
- `simp_lemmas`: Proper use of simp lemmas and simp set management
- `api_design`: Using existing API lemmas instead of manual construction
- `other`: Anything not covered above


## Context files: `data/contexts/pr_{N}.json`

One file per PR that has had its context extracted. Each holds the complete contents of every `.lean` file the PR touched, captured at two points in time. The 100 dev-set PRs come to 46MB; the held-out set's contexts are alongside them.

### Schema

```json
{
  "pr_number": 33656,
  "base_commit_sha": "0763a3babcee...",
  "first_commit_sha": "fbd3f3ce62a7...",
  "last_commit_sha": "d0fa930e7337...",
  "initial_files": [
    {"path": "Mathlib/Data/Nat/Choose/Sum.lean", "content": "...full file..."}
  ],
  "final_files": [
    {"path": "Mathlib/Data/Nat/Choose/Sum.lean", "content": "...full file..."}
  ],
  "lean_file_count": 1,
  "fetch_errors": []
}
```

### The three SHAs

- `base_commit_sha`: the mathlib commit before the PR (the parent of `first_commit_sha`). Use this to pin a Lean LSP or browse mathlib at the state the author was working against. 99 unique values across the 100 dev-set PRs.
- `first_commit_sha`: the PR's first commit. `initial_files` holds the file contents at this point, the code the author first submitted for review.
- `last_commit_sha`: the PR's last commit. `final_files` holds the contents here, the code that was accepted and merged via Bors.

### `initial_files` / `final_files`

Parallel arrays with the same paths in the same order. Each entry:

- `path`: location in the mathlib tree (e.g. `Mathlib/Data/Nat/Choose/Sum.lean`)
- `content`: full file text, or `null` if the file didn't exist at that commit

`null` content means:
- in `initial_files`, a new file created during the PR (60 cases in the dev set)
- in `final_files`, a file deleted by the PR (3 cases in the dev set)

### Scale (dev set)

- 710 `.lean` files tracked across 100 PRs
- per PR: min 1, max 87, median 3, mean 7.1 files
- zero fetch errors

### Relationship to eval rows

The 123 declaration-level rows in `proofjudge_eval.jsonl` map to 100 context files. 23 PRs have two or more declarations each, and one context file (e.g. `pr_32870.json`) serves every declaration evaluated from that PR.

## AI authorship in the corpus

Searching the raw review record (`data/extraction/pr_*.json`, 1,904 PRs) for AI-authorship language turns up very little, and most of what it does turn up isn't what it looks like. Recorded here so a future grep doesn't raise a false alarm:

- PR #32870: a reviewer asks the author to "reduce the AI generated commit messages". This PR supplies four eval declarations and is one of the project's golden examples. The comment is about commit messages, which never appear in any judge input, and says nothing about how the proofs were written.
- PR #32959: the one substantive case. A reviewer asked whether a proof was AI-generated, then struck the question through. The author confirmed that Copilot autocompletion had propagated their errors. If this is ever cited, quote it with the strikethrough.
- PR #29728: a reviewer asked the author to disclose AI assistance; the author removed "AI-generated comments". This is about code comments, not proofs.
- Three more keyword hits are false positives: a reviewer joking that they are "in fact not a LLM", `utm_source=chatgpt.com` inside a pasted Wikipedia URL, and mentions of GitHub's Copilot review-suggestion bot.

The word "generated" is common in mathlib in senses that have nothing to do with AI (`simps`-generated lemmas, generated declarations in linter output, finitely generated ideals), so it's useless as a search term.

Otherwise the corpus is human-authored, and partly that's by construction: `qualifies_for_extraction` (`models/pr.py`) requires a merged PR, and submissions rejected for being machine-written are closed without merging, so they were never scanned.

## Loading the Data

### Plain Python

```python
import json
from pathlib import Path

# Load PR-level eval rows
with open("data/dataset/proofjudge_eval_pr_level.jsonl") as f:
    eval_rows = [json.loads(line) for line in f]

# Load a context file
def load_context(pr_number: int) -> dict:
    path = Path(f"data/contexts/pr_{pr_number}.json")
    return json.loads(path.read_text())

# Get the initial version of a specific file
ctx = load_context(33656)
for file_snap in ctx["initial_files"]:
    if file_snap["path"] == "Mathlib/Data/Nat/Choose/Sum.lean":
        print(file_snap["content"])
```

### With Pydantic models (from this repo)

```python
from pathlib import Path
from proofjudge.models.context import PRContext
from proofjudge.storage.jsonl import read_json_file

ctx = read_json_file(Path("data/contexts/pr_33656.json"), PRContext)
ctx.base_commit_sha       # "0763a3babceeb9dcde4552ede5db93ac6de6299e"
ctx.initial_files[0].path     # "Mathlib/Data/Nat/Choose/Sum.lean"
ctx.initial_files[0].content  # full file text, or None for new files
ctx.lean_file_count           # 1
ctx.fetch_errors              # []
```

### Assembling judge input for one eval row

```python
import json
from pathlib import Path

# 1. Load the eval row
with open("data/dataset/proofjudge_eval_pr_level.jsonl") as f:
    for line in f:
        row = json.loads(line)
        if row["pr_number"] == 33656:
            break

# 2. Load context
ctx = json.loads(Path(f"data/contexts/pr_{row['pr_number']}.json").read_text())

# 3. The judge sees (for each blind evaluation):
#    - row["pr_title"]            → intent
#    - row["file_paths"]          → where in the codebase
#    - ctx["base_commit_sha"]     → mathlib version (for tool access)
#    - ctx["initial_files"]       → full file contents (initial version)
#    - ctx["final_files"]         → full file contents (final version)

# 4. The judge scores initial and final independently.
#    Success = score(final) > score(initial)

# 5. Answer key for deeper analysis:
#    - row["declarations"][i]["rejection_reasons"]
#    - row["declarations"][i]["feedback_categories"]
#    - row["declarations"][i]["key_changes"]
```

## Other Data Files

### `data/extraction/pr_{N}.json`

Raw PR data from GitHub: review comments, issue comments, formal reviews, commits, files changed. Contains the actual reviewer feedback text. Useful for ground-truth analysis but not needed for the judge eval.

### `data/parsing/pr_{N}.json`

Parsed proof blocks from the `.lean` files at both commits, matched into initial/final pairs by declaration name.

### `data/summarization/pr_{N}.json`

LLM classification (HIGH_VALUE / LOW_VALUE / CONTEXTUAL) and summarization of each proof pair. Contains the `rejection_reasons`, `feedback_categories`, and `key_changes` that appear in the eval rows.

### `data/proofjudge.db`

SQLite database tracking pipeline state: which PRs have been discovered, enriched, extracted, parsed, summarized, assembled, and context-extracted. Used for resumability; not needed to consume the dataset.
