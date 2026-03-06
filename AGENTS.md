# ProofJudge Dataset Mining — Architecture & Tooling Decisions

## Project Goal

Mine `leanprover-community/mathlib4` PRs to extract triplets of:
- **rejected_initial_proof**: The proof code as it appeared in the first push of the PR
- **accepted_final_proof**: The proof code in the final merged version
- **summarized_reasons_for_rejection**: LLM-generated summary of all reviewer feedback explaining why the initial version was insufficient

Target: build a large dataset, then curate ~40 high-quality examples for initial evaluation, expanding over time.

## Tooling Stack

| Tool | Choice | Notes |
|------|--------|-------|
| Language | Python 3.12+ | Modern type syntax, broad ecosystem |
| Package manager | `uv` | Fast, reproducible |
| Linting | `ruff` | Linting + formatting |
| Type checking | `pyright` | Strict mode preferred |
| HTTP/GitHub API | TBD (httpx, requests, or gh CLI) | Decide during investigation |
| LLM summarization | Anthropic Agent SDK | For reviewer comment summarization |
| Data storage | JSONL (primary) + SQLite (index/query) | JSONL for processing pipeline, SQLite for queryability |

## Key Design Requirements

### Resumability
The mining pipeline must support restart-after-failure without losing progress. Every successfully processed PR should be persisted before moving to the next. The pipeline should detect what's already been processed and skip it on restart.

### Reproducibility
This codebase will be open-sourced alongside the paper. All methodology should be transparent and reproducible:
- Typed, linted, well-structured code
- Clear configuration (no magic constants buried in code)
- Deterministic pipeline steps where possible

### Data Pipeline Shape
1. **Crawl**: Fetch PR metadata from GitHub API (paginated, resumable)
2. **Filter**: Identify PRs with genuine revision cycles (not bot merges, not closed-and-reopened-elsewhere)
3. **Extract**: Pull initial and final proof diffs for qualifying PRs
4. **Summarize**: Use LLM to summarize reviewer feedback into rejection reasons
5. **Store**: Persist triplets as JSONL, index in SQLite

## Target Repository

- **Repo**: `leanprover-community/mathlib4`
- **Scale**: ~18k+ PRs, expect to filter down significantly
- **Complication**: Some PRs appear "closed" but were actually accepted and merged via a different committer's commit. Investigation needed before building filters.

## Open Questions (To Resolve During Investigation)

- How to reliably distinguish genuine revision PRs from bot/CI activity?
- What does "closed but merged by someone else" look like in the API data?
- How to extract proof-level diffs (not just file-level) from PR history?
- What's the typical review cycle structure? (single round vs. multi-round)
- How much reviewer feedback is inline comments vs. top-level PR comments?
