"""Eval-set construction and label verification.

The `pipeline` package mines a corpus of proof pairs from mathlib PRs. This
package turns that corpus into a *held-out eval set* you can trust:

    universe   build the candidate pool from parsed + summarized pairs
    select     stratified selection with the exclusion filters
    hygiene    mechanical defect checks (no LLM required)
    blind      emit blinded adjudication tasks + a private answer key
    verdicts   decode adjudication results, pool studies, report failures

The adjudication itself runs as a Claude Code Workflow (see workflows/) because
it needs many independent model judgements; everything else is plain Python.
"""
