"""Mechanical defect checks — everything findable without an LLM.

Blind adjudication answers "does the label mark the better proof". These checks
answer the cheaper question first: "is this row well-formed at all". Run them
before spending adjudication budget; there is no point judging a row you already
know to drop.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from proofjudge.evalset.lean_text import code_only, signature
from proofjudge.evalset.select import NON_MATHEMATICAL_PATH, is_metaprogram

CHECKS = (
    "identical_after_comment_strip",
    "unbalanced_brackets",
    "declaration_name_absent",
    "duplicate_final_proof",
    "duplicate_initial_proof",
    "signature_actually_differs",
    "empty_proof_body",
    "line_count_mismatch",
    "non_mathematical_path",
    "metaprogram_code",
)


def _balanced(src: str) -> bool:
    closing = {")": "(", "]": "[", "}": "{", "⟩": "⟨"}
    stack: list[str] = []
    for ch in code_only(src):
        if ch in "([{⟨":
            stack.append(ch)
        elif ch in closing:
            if not stack or stack[-1] != closing[ch]:
                return False
            stack.pop()
    return not stack


def audit(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Return {check_name: [offending "pr:declaration", ...]}.

    Findings are always named, never counted — a count tells you something is
    wrong but not what, and several of these turned out to be false alarms in
    the check rather than defects in the data.
    """
    f: dict[str, list[str]] = {c: [] for c in CHECKS}
    by_final: dict[str, list[str]] = defaultdict(list)
    by_initial: dict[str, list[str]] = defaultdict(list)

    for r in rows:
        tag = f"{r['pr_number']}:{r['declaration_name']}"
        ip, fp = r["initial_proof"], r["final_proof"]

        if code_only(ip) == code_only(fp):
            f["identical_after_comment_strip"].append(tag)
        for side, src in (("initial", ip), ("final", fp)):
            if not _balanced(src):
                f["unbalanced_brackets"].append(f"{tag} ({side})")
        short = r["declaration_name"].split(".")[-1]
        for side, src in (("initial", ip), ("final", fp)):
            if short not in src:
                f["declaration_name_absent"].append(f"{tag} ({side})")
        # `where`-aware: splitting only on ':=' misreports where-form
        # declarations entirely as signature.
        if signature(ip) != signature(fp):
            f["signature_actually_differs"].append(tag)
        if not code_only(ip) or not code_only(fp):
            f["empty_proof_body"].append(tag)
        ai, af = len(ip.rstrip().splitlines()), len(fp.rstrip().splitlines())
        if abs(ai - r["initial_line_count"]) > 1 or abs(af - r["final_line_count"]) > 1:
            f["line_count_mismatch"].append(
                f"{tag} (stored {r['initial_line_count']}/{r['final_line_count']}, "
                f"actual {ai}/{af})"
            )
        if NON_MATHEMATICAL_PATH.search(r["file_path"]):
            f["non_mathematical_path"].append(f"{tag} ({r['file_path']})")
        if is_metaprogram(fp):
            f["metaprogram_code"].append(tag)

        by_final[code_only(fp)].append(tag)
        by_initial[code_only(ip)].append(tag)

    for group in by_final.values():
        if len(group) > 1:
            f["duplicate_final_proof"].append(" == ".join(group))
    for group in by_initial.values():
        if len(group) > 1:
            f["duplicate_initial_proof"].append(" == ".join(group))
    return f


def format_report(findings: dict[str, list[str]], limit: int = 12) -> str:
    lines = []
    total = 0
    for c in CHECKS:
        v = findings.get(c, [])
        total += len(v)
        lines.append(f"{c}: {len(v)}")
        for x in v[:limit]:
            lines.append(f"    {x}")
        if len(v) > limit:
            lines.append(f"    ... and {len(v) - limit} more")
    lines.append(f"\ntotal findings: {total}")
    return "\n".join(lines)
