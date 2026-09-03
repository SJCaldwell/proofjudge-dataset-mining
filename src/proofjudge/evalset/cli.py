"""CLI for eval-set construction. Wired into the main CLI as `evalset`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from proofjudge.evalset import anchors, blind, hygiene, universe, verdicts
from proofjudge.evalset.select import Row, dedupe_pool, draw, eligible, to_row

app = typer.Typer(help="Build and verify a held-out eval set.")

DATA = Path("data")
WORK = DATA / "evalset"


def _held_out_against(path: Path | None) -> tuple[set[int], set[tuple[str, str]]]:
    """PRs and (declaration, file) pairs the new set must not overlap.

    Declaration-level exclusion matters: PR-level alone missed three cases of
    the same declaration in the same file edited by two different PRs.
    """
    if not path or not path.exists():
        return set(), set()
    prs: set[int] = set()
    df: set[tuple[str, str]] = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        prs.add(rec["pr_number"])
        for d in rec.get("declarations", [rec]):
            df.add((d["declaration_name"], d["file_path"]))
    return prs, df


@app.command()
def select(
    n_api: Annotated[int, typer.Option(help="rows tagged api_design")] = 60,
    n_other: Annotated[int, typer.Option(help="rows not tagged api_design")] = 190,
    against: Annotated[Path, typer.Option(help="existing eval jsonl to hold out against")] = None,
    out: Annotated[Path, typer.Option()] = WORK / "candidate_rows.jsonl",
) -> None:
    """Draw a stratified eval set from the candidate universe."""
    cands = universe.load_or_build(DATA, WORK / "universe.json")
    prs, df = _held_out_against(against)
    ok, rej = eligible(cands, DATA, prs, df)
    ok, rej2 = dedupe_pool(ok, DATA)
    rej.update(rej2)

    typer.echo("filter funnel:")
    for why, k in sorted(rej.items(), key=lambda x: -x[1]):
        typer.echo(f"   -{k:>6}  {why}")

    api = [c for c in ok if "api_design" in c.cats]
    other = [c for c in ok if "api_design" not in c.cats]
    typer.echo(
        f"\neligible: api_design {len(api)} rows / {len({c.pr for c in api})} PRs"
        f"   other {len(other)} rows / {len({c.pr for c in other})} PRs"
    )

    used: set[int] = set()
    rows: list[Row] = [to_row(c, DATA, "B") for c in draw(api, n_api, used)]
    rows += [to_row(c, DATA, "C") for c in draw(other, n_other, used)]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r.__dict__) for r in rows) + "\n")
    api_frac = sum(1 for r in rows if "api_design" in r.feedback_categories) / len(rows)
    typer.echo(
        f"\nselected {len(rows)} rows / {len({r.pr_number for r in rows})} PRs"
        f"   api_design {api_frac:.1%}"
    )
    typer.echo(f"wrote {out}")


@app.command()
def audit(rows: Annotated[Path, typer.Option()] = WORK / "candidate_rows.jsonl") -> None:
    """Run the mechanical hygiene checks. No LLM, no cost."""
    data = [json.loads(line) for line in rows.read_text().splitlines() if line.strip()]
    typer.echo(f"hygiene audit — {len(data)} rows\n" + "=" * 60)
    typer.echo(hygiene.format_report(hygiene.audit(data)))


@app.command("emit-tasks")
def emit_tasks(
    rows: Annotated[Path, typer.Option()] = WORK / "candidate_rows.jsonl",
    prefix: Annotated[str, typer.Option()] = "blind",
    agents_per_replicate: Annotated[int, typer.Option()] = 12,
    reference: Annotated[
        Path, typer.Option(help="eval jsonl to draw calibration anchors from")
    ] = None,
) -> None:
    """Write the blinded task file, answer key, and agent batches."""
    data = [json.loads(line) for line in rows.read_text().splitlines() if line.strip()]
    stats = blind.emit(data, WORK, prefix, agents_per_replicate)
    typer.echo(json.dumps(stats, indent=2))
    if reference:
        (WORK / "anchors.md").write_text(anchors.build(reference, DATA))
        typer.echo(f"wrote {WORK / 'anchors.md'}")
    typer.echo(
        f"\nnow run the adjudication workflow (see docs/REPRODUCING.md),"
        f"\nthen: proofjudge evalset verify --prefix {prefix}"
    )


@app.command()
def verify(
    prefix: Annotated[str, typer.Option()] = "blind",
    rows: Annotated[Path, typer.Option()] = WORK / "candidate_rows.jsonl",
    journal: Annotated[Path, typer.Option(help="recover verdicts from a Workflow journal")] = None,
    out: Annotated[Path, typer.Option()] = WORK / "verified_rows.jsonl",
) -> None:
    """Decode verdicts, report label support, and write the verified set."""
    key = json.loads((WORK / f"{prefix}_key.json").read_text())
    found = (
        verdicts.load_verdicts_from_journal(journal)
        if journal
        else verdicts.load_verdicts(WORK, prefix)
    )
    found = {t: v for t, v in found.items() if t in key}
    missing = [t for t in key if t not in found]
    typer.echo(
        f"verdicts {len(found)}/{len(key)}"
        + (f"   MISSING {len(missing)}" if missing else "   complete")
    )
    if missing:
        raise typer.Exit(code=1)

    data = [json.loads(line) for line in rows.read_text().splitlines() if line.strip()]
    strata = {(r["pr_number"], r["declaration_name"]): r.get("stratum", "-") for r in data}
    per = verdicts.decode(found, key)
    rep = verdicts.report(per, strata)

    typer.echo(f"\nposition bias {verdicts.position_bias(found):.3f} (0.500 = none)")
    typer.echo("unanimity     " + "  ".join(f"{k} {v:.1%}" for k, v in rep["unanimity"].items()))
    typer.echo(
        f"\nlabel-supported {rep['supported']}/{rep['n']} = "
        f"{rep['supported_rate']:.1%} +/- {rep['ci95_pt']:.1f}pt"
    )
    for st, s in rep.get("by_stratum", {}).items():
        typer.echo(f"   stratum {st}: {s['n']:>4} rows, {s['supported_rate']:.1%} supported")
    typer.echo("\nfailures by type:")
    for g, items in rep["failures"].items():
        typer.echo(f"  {g}: {len(items)}")
        for pr, decl in items:
            typer.echo(f"     {pr}:{decl}")

    failed = {tuple(p) for p in rep["failed_pairs"]}
    kept = [r for r in data if (r["pr_number"], r["declaration_name"]) not in failed]
    out.write_text("\n".join(json.dumps(r) for r in kept) + "\n")
    typer.echo(f"\n{len(data)} -> {len(kept)} rows after dropping failures")
    typer.echo(f"wrote {out}")
