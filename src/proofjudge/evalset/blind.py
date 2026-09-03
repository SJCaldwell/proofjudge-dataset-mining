"""Emit blinded adjudication tasks and a private answer key.

Blinding is enforced by the *data on disk*, not by prompt instruction: the task
file's rows carry only `task_id`, `declaration`, `file_path`, `proof_a` and
`proof_b`. There is no `initial_proof`/`final_proof` field name, no
`rejection_reasons`, no line counts, no category tags — an adjudicator cannot
infer the answer from a field name because the field names carry none.

`rep` is deliberately absent from the task file too: replicate 0 always puts the
accepted proof in slot A, so exposing it would leak the answer outright.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

REPLICATES = 3


def _accepted_is_a(pr: int, decl: str, rep: int) -> bool:
    """Order balancing: rep 0 accepted-as-A, rep 1 accepted-as-B, rep 2 by a
    stable hash. Every pair is seen both ways, so position bias becomes a
    measurable quantity rather than a nuisance averaged away."""
    if rep == 0:
        return True
    if rep == 1:
        return False
    return hashlib.sha256(f"{pr}:{decl}".encode()).digest()[0] % 2 == 0


def emit(
    rows: list[dict[str, Any]], out_dir: Path, prefix: str, agents_per_replicate: int = 12
) -> dict[str, int]:
    """Write <prefix>_tasks.jsonl, _key.json and _batches.json.

    Agents are partitioned by replicate, so no agent ever sees the same pair
    twice and cannot recognise a pair it has already judged.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, str]] = []
    key: dict[str, dict[str, Any]] = {}
    for r in sorted(rows, key=lambda r: (r["pr_number"], r["declaration_name"])):
        for rep in range(REPLICATES):
            a_is_accepted = _accepted_is_a(r["pr_number"], r["declaration_name"], rep)
            tid = f"{prefix[0]}{len(tasks):04d}"
            tasks.append(
                {
                    "task_id": tid,
                    "declaration": r["declaration_name"],
                    "file_path": r["file_path"],
                    "proof_a": (r["final_proof"] if a_is_accepted else r["initial_proof"]).strip(),
                    "proof_b": (r["initial_proof"] if a_is_accepted else r["final_proof"]).strip(),
                }
            )
            key[tid] = {
                "pr": r["pr_number"],
                "decl": r["declaration_name"],
                "stratum": r.get("stratum", "-"),
                "rep": rep,
                "accepted_is_a": a_is_accepted,
            }

    leaking = [
        k
        for k in tasks[0]
        if k not in ("task_id", "declaration", "file_path", "proof_a", "proof_b")
    ]
    if leaking:
        raise AssertionError(f"task file would leak provenance fields: {leaking}")

    batches: list[list[str]] = []
    for rep in range(REPLICATES):
        ids = sorted(
            [t for t, v in key.items() if v["rep"] == rep], key=lambda t: (key[t]["stratum"], t)
        )
        groups: list[list[str]] = [[] for _ in range(agents_per_replicate)]
        for i, t in enumerate(ids):
            groups[i % agents_per_replicate].append(t)
        batches += groups
    for b in batches:
        pairs = [(key[t]["pr"], key[t]["decl"]) for t in b]
        if len(pairs) != len(set(pairs)):
            raise AssertionError("a batch contains the same pair twice")

    (out_dir / f"{prefix}_tasks.jsonl").write_text("\n".join(json.dumps(t) for t in tasks) + "\n")
    (out_dir / f"{prefix}_key.json").write_text(json.dumps(key, indent=2))
    (out_dir / f"{prefix}_batches.json").write_text(json.dumps(batches))

    n_a = sum(1 for v in key.values() if v["accepted_is_a"])
    return {
        "pairs": len(rows),
        "tasks": len(tasks),
        "batches": len(batches),
        "accepted_as_a": n_a,
        "accepted_as_b": len(key) - n_a,
    }
