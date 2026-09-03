"""Stratified selection of an eval set from the candidate universe.

Every exclusion here was added because it caused a measured problem. The
comments say which — do not remove one without knowing what it was for.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from proofjudge.evalset.lean_text import code_only
from proofjudge.evalset.universe import Candidate, proof_text, summary_record

if TYPE_CHECKING:
    from pathlib import Path

# Paths whose contents are not mathematical proofs: linters, CLI tools, tactic
# implementations, competition archives. These leak into the corpus because
# INFRA_PATH_PREFIXES is applied in `is_proof_touching` (a PR-level any() check)
# but NOT in `parse_single_pr`, which parses every .lean file in a qualifying PR.
# Measured: such rows aligned at 31.6% and inverted at 52.6% under a
# proof-quality rubric, against 60.6%/24.7% for real proofs.
NON_MATHEMATICAL_PATH = re.compile(
    r"^(scripts|Cache|LongestPole|test|Shake|ImportGraph|Counterexamples|Archive)/"
    r"|^\.github/|^lakefile"
    r"|^Mathlib/(Tactic|Util|Lean|Mathport|Testing)/|/Linter/"
)
# Monadic metaprogram code that lives outside those paths.
_DO = re.compile(r"(?<![A-Za-z_])do(?![A-Za-z_])")
_ELAB = re.compile(
    r"\b(MetaM|CommandElabM|TacticM|CoreM|TermElabM|SimpM|IO)\b|TSyntax|Syntax\b|Expr\b"
)


def is_metaprogram(final_proof: str) -> bool:
    return bool(_DO.search(final_proof) and _ELAB.search(final_proof))


@dataclass
class Row:
    """One eval row. Mirrors the published schema plus selection provenance."""

    pr_number: int
    declaration_name: str
    declaration_kind: str
    file_path: str
    initial_proof: str
    final_proof: str
    rejection_reasons: str
    feedback_categories: list[str]
    key_changes: list[str]
    initial_line_count: int
    final_line_count: int
    line_count_delta: int
    signature_changed: bool
    stratum: str
    length_ratio: float
    code_similarity: float
    created_at: str


def eligible(
    cands: list[Candidate],
    data_dir: Path,
    exclude_prs: set[int],
    exclude_decl_file: set[tuple[str, str]],
    *,
    min_initial_lines: int = 5,
    require_shrinking: bool = True,
) -> tuple[list[Candidate], dict[str, int]]:
    """Apply every exclusion filter. Returns (survivors, rejection tally)."""
    rej: dict[str, int] = defaultdict(int)
    stage1: list[Candidate] = []
    for c in cands:
        if c.verdict != "HIGH_VALUE":
            rej["not HIGH_VALUE"] += 1
        elif c.sig_changed:
            # Measured: signature-changed pairs invert at 38.5% vs 10.9%. When
            # the statement changes, the initial proof's shape is forced rather
            # than chosen, so it is not a clean test of judgement.
            rej["signature_changed"] += 1
        elif c.initial_lines < min_initial_lines:
            rej[f"initial < {min_initial_lines} lines"] += 1
        elif not c.explicit_fb:
            rej["no explicit review feedback"] += 1
        elif require_shrinking and c.ratio >= 1.0:
            # Same-or-longer pairs: blind readers supported the label on only
            # 43.3% of them, against 89-93% for shrinking pairs. Near-identical
            # textually, frequently lateral, and the label survived only because
            # the annotator read review comments the proof text lacks.
            rej["same-or-longer (not labelable from proof text)"] += 1
        elif c.pr in exclude_prs:
            rej["PR in the held-out-against set"] += 1
        elif NON_MATHEMATICAL_PATH.search(c.file):
            rej["non-mathematical path"] += 1
        else:
            stage1.append(c)

    # Text-dependent checks need the proofs loaded, so they run second.
    survivors: list[Candidate] = []
    for c in stage1:
        if (c.decl, c.file) in exclude_decl_file:
            # PR-level exclusion alone missed 3 of these: the same declaration
            # in the same file, edited by two different PRs.
            rej["declaration+file in the held-out-against set"] += 1
            continue
        try:
            ip, fp = proof_text(data_dir, c.pr, c.decl, c.file)
        except KeyError:
            rej["no parsing record"] += 1
            continue
        if code_only(ip) == code_only(fp):
            rej["identical once comments are stripped"] += 1
            continue
        if is_metaprogram(fp):
            rej["metaprogram code"] += 1
            continue
        if not (summary_record(data_dir, c.pr, c.decl, c.file) or {}).get("summary", "").strip():
            rej["empty rejection_reasons"] += 1
            continue
        survivors.append(c)
    return survivors, dict(rej)


def dedupe_pool(cands: list[Candidate], data_dir: Path) -> tuple[list[Candidate], dict[str, int]]:
    """Drop duplicate declarations *before* drawing, not after.

    The same declaration can appear under two PRs (one superseding the other)
    with byte-identical proofs. Deduping the pool lets the freed slot be
    backfilled; dropping post-hoc just shrinks the set. Keeps the higher PR
    number — the version that actually landed.
    """
    rej: dict[str, int] = defaultdict(int)
    seen_declfile: set[tuple[str, str]] = set()
    seen_proof: set[str] = set()
    out: list[Candidate] = []
    for c in sorted(cands, key=lambda c: -c.pr):
        _, fp = proof_text(data_dir, c.pr, c.decl, c.file)
        pk = code_only(fp)
        if (c.decl, c.file) in seen_declfile:
            rej["duplicate declaration+file in pool"] += 1
            continue
        if pk in seen_proof:
            rej["duplicate final proof in pool"] += 1
            continue
        seen_declfile.add((c.decl, c.file))
        seen_proof.add(pk)
        out.append(c)
    return out, dict(rej)


def draw(pool: list[Candidate], target: int, used_prs: set[int]) -> list[Candidate]:
    """Round-robin across PR-creation years so the set is not recency-skewed.

    Within a year, prefer candidates with more quoted reviewer text — those
    have the strongest human signal behind the label. Fully deterministic:
    no RNG, so a rerun reproduces the same set.
    """
    by_year: dict[str, list[Candidate]] = defaultdict(list)
    for c in pool:
        by_year[c.created[:4]].append(c)
    for y in by_year:
        by_year[y].sort(key=lambda c: (-c.n_quotes, c.pr, c.decl or ""))
    years = sorted(by_year)
    idx = dict.fromkeys(years, 0)
    out: list[Candidate] = []
    while len(out) < target:
        progressed = False
        for y in years:
            if len(out) >= target:
                break
            while idx[y] < len(by_year[y]):
                c = by_year[y][idx[y]]
                idx[y] += 1
                if c.pr in used_prs:
                    continue
                used_prs.add(c.pr)
                out.append(c)
                progressed = True
                break
        if not progressed:
            break
    return out


def to_row(c: Candidate, data_dir: Path, stratum: str) -> Row:
    ip, fp = proof_text(data_dir, c.pr, c.decl, c.file)
    s = summary_record(data_dir, c.pr, c.decl, c.file) or {}
    return Row(
        pr_number=c.pr,
        declaration_name=c.decl,
        declaration_kind=c.kind,
        file_path=c.file,
        initial_proof=ip,
        final_proof=fp,
        rejection_reasons=s.get("summary", ""),
        feedback_categories=s.get("categories", []),
        key_changes=s.get("key_changes", []),
        initial_line_count=c.initial_lines,
        final_line_count=c.final_lines,
        line_count_delta=c.final_lines - c.initial_lines,
        signature_changed=False,
        stratum=stratum,
        length_ratio=round(c.ratio, 4),
        code_similarity=round(c.sim, 4),
        created_at=c.created,
    )
