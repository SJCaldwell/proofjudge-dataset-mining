"""Lean 4 source-text utilities shared across eval-set construction.

Comment stripping is the load-bearing one: two proofs that differ only in
comments are not a usable pair, and comment text also inflates any similarity
measure. Lean 4 block comments nest, so a regex is not sufficient.
"""

import difflib
import re

_WS = re.compile(r"\s+")


def strip_comments(src: str) -> str:
    """Remove Lean 4 comments: nestable /- -/ (incl. /-- -/) and -- to EOL.

    String literals are preserved, so a `--` inside a string is not mistaken
    for a comment.
    """
    out: list[str] = []
    i, n, depth, in_str = 0, len(src), 0, False
    while i < n:
        if in_str:
            if src[i] == "\\" and i + 1 < n:
                out.append(src[i : i + 2])
                i += 2
                continue
            if src[i] == '"':
                in_str = False
                out.append('"')
                i += 1
                continue
            out.append(src[i])
            i += 1
            continue
        if depth > 0:
            if src.startswith("/-", i):
                depth += 1
                i += 2
                continue
            if src.startswith("-/", i):
                depth -= 1
                i += 2
                continue
            i += 1
            continue
        if src.startswith("/-", i):
            depth += 1
            i += 2
            continue
        if src.startswith("--", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src[i] == '"':
            in_str = True
            out.append('"')
            i += 1
            continue
        out.append(src[i])
        i += 1
    return "".join(out)


def code_only(src: str) -> str:
    """Comment-free, whitespace-normalized source — the canonical form for
    equality checks between two versions of a declaration."""
    return _WS.sub(" ", strip_comments(src)).strip()


def _split_at_top_level(text: str) -> int:
    """Index of the top-level `:=` or `where`, whichever comes first.

    `where`-form declarations (`instance foo : Bar where ...`) have no `:=`.
    Splitting only on `:=` misreports their entire body as signature — that
    produced 11 false 'signature changed' findings before it was fixed.
    """
    depth = 0
    for i, ch in enumerate(text):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif depth == 0:
            if text.startswith(":=", i):
                return i
            if (
                text.startswith("where", i)
                and (i == 0 or not text[i - 1].isalnum())
                and (i + 5 >= len(text) or not text[i + 5].isalnum())
            ):
                return i
    return -1


def signature(src: str) -> str:
    """The declaration's statement — everything before the proof body."""
    t = strip_comments(src)
    i = _split_at_top_level(t)
    return _WS.sub(" ", t if i < 0 else t[:i]).strip()


def body(src: str) -> str:
    """The proof body — everything after the statement."""
    t = strip_comments(src)
    i = _split_at_top_level(t)
    if i < 0:
        return _WS.sub(" ", t).strip()
    skip = 2 if t.startswith(":=", i) else 0
    return _WS.sub(" ", t[i + skip :]).strip()


def code_similarity(initial: str, final: str) -> float:
    """Similarity of two proof *bodies*, comments stripped.

    Body-only rather than whole-declaration: the signature is identical on
    every pair we keep, so including it inflates similarity — most on the
    heavily-rewritten pairs, where it matters most.
    """
    a, b = body(initial), body(final)
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
