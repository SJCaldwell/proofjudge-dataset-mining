"""Build the calibration anchors shown to blind adjudicators.

Four anchors, chosen to demonstrate all three verdicts. Getting this mix right
matters more than it looks: an earlier version used three anchors that all
resolved "the second one is better", which taught the adjudicator to go find an
improvement and biased it against the `comparable` verdict — the exact verdict
the study was trying to measure.

The fourth anchor must be a genuine *lateral* change with real code differences.
A comment-only diff is useless here: it teaches "comparable means byte-identical".
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# (declaration, why-it-illustrates-what). Replace these for a different corpus —
# they are specific mathlib declarations, not a general fixture.
DEFAULT_ANCHORS = [
    (
        "baseChange",
        "clear",
        "A nine-line manual structure instance is replaced by a single existing "
        "library combinator. This is library leverage, not mere brevity.",
    ),
    (
        "measure_preimage_eq_zero_iff_of_countable",
        "clear",
        "A hand-rolled calc chain over a countable union is replaced by the two "
        "library lemmas that state exactly that fact.",
    ),
    (
        "zeroLocus_vanishingIdeal_eq_closure",
        "subtle",
        "A modest tightening. Real, but nothing like the first two.",
    ),
]
# The comparable anchor is drawn from the corpus rather than the reference set,
# because a lateral change is by definition not a labelled improvement.
COMPARABLE_ANCHOR = (
    11986,
    "Odd.add_odd",
    "The bound variables are renamed and the witness is written in the other "
    "order. It is the same proof, with the same tactics in the same structure. "
    "You could argue version 2 avoids shadowing the outer variable names and is "
    'a shade tidier — but as a proof neither is better, and "comparable" is '
    "the correct verdict. Do not talk yourself into a preference merely because "
    "a difference exists.",
)

_TAIL = """
# What these calibration examples do and do not tell you

They show what each verdict looks like. They say **nothing** about how often each
verdict is correct. They were hand-picked to be clear, and they are not a sample
of the pairs you will judge.

In the pairs you judge, a substantial fraction may be genuinely comparable, and in
some, Proof A may be the better one. Do not assume an improvement is present and go
looking for it. If the difference is lateral — a rename, a reformat, an equivalent
tactic, a change forced by something outside the proof — answer "comparable". If the
proof that looks earlier is actually better, say so. Judge what is in front of you.
"""


def build(reference_eval: Path, data_dir: Path) -> str:
    """Render anchors.md from a reference eval set plus the parsed corpus."""
    ref: dict[str, dict] = {}
    for line in reference_eval.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for d in rec.get("declarations", [rec]):
            ref[d["declaration_name"]] = d

    out = [
        "# Calibration examples",
        "",
        "Four pairs where the Mathlib community's preference is known. They are shown",
        "here **labelled**, only so you know what each verdict looks like. The pairs you",
        "judge are NOT labelled.",
        "",
    ]
    n = 0
    for decl, kind, why in DEFAULT_ANCHORS:
        d = ref.get(decl)
        if d is None:
            continue
        n += 1
        head = (
            "version 2 is clearly better"
            if kind == "clear"
            else "version 2 is better, but only mildly"
        )
        out += [
            f"## Calibration {n} — {head} (`{decl}`)",
            "Version 1:",
            "```lean",
            d["initial_proof"].strip(),
            "```",
            "Version 2:",
            "```lean",
            d["final_proof"].strip(),
            "```",
            why,
            "",
        ]

    pr, decl, why = COMPARABLE_ANCHOR
    p = data_dir / "parsing" / f"pr_{pr}.json"
    if p.exists():
        pair = next(
            (x for x in json.loads(p.read_text())["pairs"] if x["declaration_name"] == decl), None
        )
        if pair:
            n += 1
            out += [
                f"## Calibration {n} — these two are COMPARABLE (`{decl}`)",
                "Version 1:",
                "```lean",
                pair["initial_proof"]["full_text"].strip(),
                "```",
                "Version 2:",
                "```lean",
                pair["final_proof"]["full_text"].strip(),
                "```",
                why,
                "",
            ]
    out.append(_TAIL)
    return "\n".join(out)
