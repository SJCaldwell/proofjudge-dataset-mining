"""Decode blind adjudication verdicts and report label support.

Verdicts arrive as `verdict: "A" | "B" | "comparable"` against a blinded task
file. Decoding needs the key to say which slot held the accepted proof.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

Pair = tuple[int, str]


def load_verdicts(out_dir: Path, prefix: str) -> dict[str, dict[str, Any]]:
    """Read per-agent verdict files written by the adjudication workflow."""
    found: dict[str, dict[str, Any]] = {}
    for f in sorted(out_dir.glob(f"{prefix}_verdicts_*.json")):
        for v in json.loads(f.read_text()).get("verdicts", []):
            found[v["task_id"]] = v
    return found


def load_verdicts_from_journal(journal: Path) -> dict[str, dict[str, Any]]:
    """Recover verdicts from a Workflow journal, if the per-agent files are gone.

    Each `{"type":"result"}` line carries an agent's full structured return.
    """
    found: dict[str, dict[str, Any]] = {}
    for line in journal.read_text().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") != "result":
            continue
        res = r.get("result") or {}
        if isinstance(res, dict):
            for v in res.get("verdicts") or []:
                found[v["task_id"]] = v
    return found


def decode(
    verdicts: dict[str, dict[str, Any]], key: dict[str, dict[str, Any]]
) -> dict[Pair, list[str]]:
    """Map each verdict back to label space: accepted / initial / comparable."""
    per: dict[Pair, list[str]] = defaultdict(list)
    for tid, v in verdicts.items():
        k = key[tid]
        if v["verdict"] == "comparable":
            picked = "comparable"
        else:
            picked = "accepted" if (v["verdict"] == "A") == k["accepted_is_a"] else "initial"
        per[(k["pr"], k["decl"])].append(picked)
    return dict(per)


def majority(picks: list[str]) -> str:
    c = Counter(picks)
    top, n = c.most_common(1)[0]
    return top if n >= 2 else "split"


def position_bias(verdicts: dict[str, dict[str, Any]]) -> float:
    """P(pick A | picked a side). 0.500 means no bias.

    Because slot assignment is balanced, a deviation here is the adjudicator
    preferring a *position*, which would invalidate every verdict.
    """
    c = Counter(v["verdict"] for v in verdicts.values())
    sides = c["A"] + c["B"]
    return c["A"] / sides if sides else float("nan")


def report(per: dict[Pair, list[str]], strata: dict[Pair, str] | None = None) -> dict[str, Any]:
    """Label-support rate overall and per stratum, plus failures by type."""
    maj = {p: majority(v) for p, v in per.items()}
    n = len(maj)
    supported = sum(1 for v in maj.values() if v == "accepted")
    se = math.sqrt((supported / n) * (1 - supported / n) / n) if n else 0.0

    groups: dict[str, list[Pair]] = {
        "unanimous initial-better": [],
        "unanimous comparable": [],
        "majority against label": [],
        "three-way split": [],
    }
    for p, m in maj.items():
        if m == "accepted":
            continue
        top = Counter(per[p]).most_common(1)[0][1]
        if m == "split":
            groups["three-way split"].append(p)
        elif top == 3:
            groups["unanimous initial-better" if m == "initial" else "unanimous comparable"].append(
                p
            )
        else:
            groups["majority against label"].append(p)

    unanimity = Counter()
    for p in per:
        top = Counter(per[p]).most_common(1)[0][1]
        unanimity["unanimous" if top == 3 else ("2-1" if top == 2 else "split")] += 1

    out: dict[str, Any] = {
        "n": n,
        "supported": supported,
        "supported_rate": supported / n if n else 0.0,
        "ci95_pt": 1.96 * se * 100,
        "unanimity": {k: v / n for k, v in unanimity.items()},
        "failures": {k: sorted(v) for k, v in groups.items()},
        "failed_pairs": sorted(p for p, m in maj.items() if m != "accepted"),
    }
    if strata:
        by_st: dict[str, list[str]] = defaultdict(list)
        for p, m in maj.items():
            by_st[strata.get(p, "-")].append(m)
        out["by_stratum"] = {
            st: {"n": len(v), "supported_rate": sum(1 for x in v if x == "accepted") / len(v)}
            for st, v in sorted(by_st.items())
        }
    return out
