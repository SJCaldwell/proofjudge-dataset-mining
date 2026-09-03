"""Build the candidate universe: every parsed proof pair, joined to its label.

The assembled dataset (`data/dataset/proofjudge.jsonl`) contains only pairs the
LLM gate marked HIGH_VALUE. Eval-set selection needs the *rejected* pairs too —
to measure what the gate excluded, and because the rejected pool is where recall
improvements would come from. So this reads `parsing/` and `summarization/`
directly rather than the assembled dataset.

Cached to JSON because computing similarity over ~11k pairs is the slow step.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from proofjudge.evalset.lean_text import code_similarity

if TYPE_CHECKING:
    from pathlib import Path

_PR_RE = re.compile(r"pr_(\d+)")


@dataclass
class Candidate:
    pr: int
    decl: str
    file: str
    kind: str
    verdict: str | None  # HIGH_VALUE / LOW_VALUE / CONTEXTUAL
    cats: list[str]
    confidence: float | None
    explicit_fb: bool | None  # did a reviewer say something about this pair
    n_quotes: int
    sig_changed: bool
    initial_lines: int
    final_lines: int
    ratio: float  # final_lines / initial_lines
    sim: float  # code-only body similarity
    author: str | None
    created: str  # ISO date of PR creation
    title: str


def build(data_dir: Path) -> list[Candidate]:
    """Join parsing + summarization + PR metadata into one candidate list."""
    summ: dict[tuple, dict] = {}
    for p in sorted((data_dir / "summarization").glob("pr_*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        for r in d.get("pair_results", []):
            summ[(d["pr_number"], r.get("declaration_name"), r.get("file_path"))] = r

    meta: dict[int, dict] = {}
    meta_path = data_dir / "enrichment" / "pr_metadata.jsonl"
    for line in meta_path.read_text().splitlines():
        if line.strip():
            m = json.loads(line)
            meta[m["number"]] = m

    out: list[Candidate] = []
    for p in sorted((data_dir / "parsing").glob("pr_*.json")):
        pr = int(_PR_RE.search(p.name).group(1))
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        m = meta.get(pr, {})
        for pair in d.get("pairs", []):
            decl, path = pair.get("declaration_name"), pair.get("file_path")
            s = summ.get((pr, decl, path))
            ip = pair["initial_proof"]["full_text"]
            fp = pair["final_proof"]["full_text"]
            il = pair["initial_proof"].get("line_count") or len(ip.splitlines())
            fl = pair["final_proof"].get("line_count") or len(fp.splitlines())
            out.append(
                Candidate(
                    pr=pr,
                    decl=decl,
                    file=path,
                    kind=pair.get("declaration_kind") or "theorem",
                    verdict=s["verdict"] if s else None,
                    cats=s["categories"] if s else [],
                    confidence=s["confidence"] if s else None,
                    explicit_fb=s["has_explicit_review_feedback"] if s else None,
                    n_quotes=len(s.get("reviewer_quotes") or []) if s else 0,
                    sig_changed=bool(pair.get("signature_changed")),
                    initial_lines=il,
                    final_lines=fl,
                    ratio=fl / max(il, 1),
                    sim=code_similarity(ip, fp),
                    author=m.get("author"),
                    created=(m.get("created_at") or "")[:10],
                    title=m.get("title", ""),
                )
            )
    return out


def load_or_build(data_dir: Path, cache: Path) -> list[Candidate]:
    if cache.exists():
        return [Candidate(**c) for c in json.loads(cache.read_text())]
    cands = build(data_dir)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([asdict(c) for c in cands]))
    return cands


def proof_text(data_dir: Path, pr: int, decl: str, file: str) -> tuple[str, str]:
    """Fetch (initial, final) proof text for one candidate."""
    d = json.loads((data_dir / "parsing" / f"pr_{pr}.json").read_text())
    for x in d["pairs"]:
        if x.get("declaration_name") == decl and x.get("file_path") == file:
            return x["initial_proof"]["full_text"], x["final_proof"]["full_text"]
    raise KeyError(f"no parsed pair for {pr}:{decl} in {file}")


def summary_record(data_dir: Path, pr: int, decl: str, file: str) -> dict | None:
    p = data_dir / "summarization" / f"pr_{pr}.json"
    if not p.exists():
        return None
    for r in json.loads(p.read_text()).get("pair_results", []):
        if r.get("declaration_name") == decl and r.get("file_path") == file:
            return r
    return None
