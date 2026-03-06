"""Lean 4 proof block extraction from source files.

Parses Lean 4 source code to extract declarations (theorem, lemma, def,
instance, example) with their signatures and proof bodies. Uses
indentation-based block detection and bracket-aware ':=' splitting.
"""

import logging

from proofjudge.models.proof import ProofBlock, ProofBlockKind

logger = logging.getLogger(__name__)

# Declaration keywords in Lean 4
DECLARATION_KEYWORDS = frozenset({"theorem", "lemma", "def", "instance", "example"})

# Modifiers that can precede a declaration keyword
MODIFIER_KEYWORDS = frozenset({
    "noncomputable",
    "protected",
    "private",
    "unsafe",
    "partial",
    "scoped",
    "public",
})

# Keywords that mark top-level block boundaries (non-declaration)
BOUNDARY_KEYWORDS = frozenset({
    "namespace",
    "section",
    "end",
    "open",
    "variable",
    "import",
    "set_option",
    "attribute",
    "class",
    "structure",
    "inductive",
    "abbrev",
    "opaque",
    "axiom",
    "mutual",
    "universe",
    "export",
    # Lean 4 commands that appear at column 0 between declarations
    "omit",
    "local",
    "alias",
    "assert_not_exists",
    "module",
    "macro",
    "syntax",
    "elab",
    "deriving",
    "suppress_compilation",
    "nonrec",
    "macro_rules",
    "run_cmd",
    "initialize",
    "initialize_simps_projections",
    "notation",
    "add_decl_doc",
    "compile_inductive%",
    "register_simp_attr",
})

_KIND_MAP: dict[str, ProofBlockKind] = {
    "theorem": ProofBlockKind.THEOREM,
    "lemma": ProofBlockKind.LEMMA,
    "def": ProofBlockKind.DEF,
    "instance": ProofBlockKind.INSTANCE,
    "example": ProofBlockKind.EXAMPLE,
}


def _lines_in_block_comments(lines: list[str]) -> set[int]:
    """Return line indices that are inside block comments.

    A line is 'inside' if the comment depth is > 0 at the START of that line.
    Handles Lean 4's nestable block comments ``/- /- ... -/ -/``.
    """
    in_comment: set[int] = set()
    depth = 0

    for i, line in enumerate(lines):
        if depth > 0:
            in_comment.add(i)

        j = 0
        while j < len(line) - 1:
            if line[j] == "/" and line[j + 1] == "-":
                depth += 1
                j += 2
            elif line[j] == "-" and line[j + 1] == "/":
                depth = max(0, depth - 1)
                j += 2
            else:
                j += 1

    return in_comment


def _skip_modifiers(words: list[str]) -> int:
    """Skip modifier keywords and return index of the first non-modifier word."""
    i = 0
    while i < len(words) and words[i] in MODIFIER_KEYWORDS:
        i += 1
    return i


def _classify_line(line: str) -> tuple[str, ...] | None:
    """Classify a line that starts at column 0.

    Returns:
        ``("decl", kind_str, name_or_empty)`` for declarations,
        ``("boundary",)`` for other block boundaries,
        ``None`` for non-boundary lines.
    """
    if not line or line[0] in (" ", "\t"):
        return None

    stripped = line.strip()
    if not stripped:
        return None

    # Line comments at column 0 act as block separators
    if stripped.startswith("--"):
        return ("boundary",)

    # Doc comments start a new block
    if stripped.startswith("/--"):
        return ("boundary",)

    # Block comment openings (not doc comments)
    if stripped.startswith("/-"):
        return ("boundary",)

    # Directives like #check, #eval
    if stripped.startswith("#"):
        return ("boundary",)

    # Strip leading @[...] attribute on same line
    clean = stripped
    if clean.startswith("@["):
        depth = 0
        for i, ch in enumerate(clean):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    clean = clean[i + 1 :].strip()
                    break
        else:
            # Unclosed bracket: attribute continues on next line
            return ("boundary",)

    if not clean:
        # Line was just an attribute — boundary before the declaration
        return ("boundary",)

    # Parse words after stripping modifiers
    words = clean.split()
    idx = _skip_modifiers(words)

    if idx >= len(words):
        # Only modifiers on this line (e.g., standalone "noncomputable")
        return ("boundary",) if idx > 0 else None

    keyword = words[idx]

    if keyword in DECLARATION_KEYWORDS:
        name = ""
        if keyword == "example":
            pass  # Examples are always unnamed
        elif idx + 1 < len(words):
            candidate = words[idx + 1]
            # Unnamed instances: next token starts with non-identifier char
            if keyword == "instance" and not (
                candidate[0].isalpha() or candidate[0] == "_"
            ):
                name = ""
            else:
                name = candidate.rstrip(":({[")
        return ("decl", keyword, name)

    if keyword in BOUNDARY_KEYWORDS:
        return ("boundary",)

    return None


def _find_body_split(text: str) -> tuple[int, str] | None:
    """Find where the signature ends and body begins.

    Searches for top-level ``:=`` or ``where`` (at bracket depth 0,
    outside comments and strings).

    Returns ``(position, ":=" or "where")`` or ``None``.
    """
    i = 0
    depth = 0
    in_string = False
    in_line_comment = False
    block_depth = 0
    length = len(text)

    while i < length:
        c = text[i]

        # Line comments
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            i += 1
            continue

        # Block comments (nestable)
        if block_depth > 0:
            if i + 1 < length and c == "/" and text[i + 1] == "-":
                block_depth += 1
                i += 2
                continue
            if i + 1 < length and c == "-" and text[i + 1] == "/":
                block_depth -= 1
                i += 2
                continue
            i += 1
            continue

        # Strings
        if in_string:
            if c == "\\" and i + 1 < length:
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
            continue

        # Detect comment/string starts
        if i + 1 < length:
            if c == "-" and text[i + 1] == "-":
                in_line_comment = True
                i += 2
                continue
            if c == "/" and text[i + 1] == "-":
                block_depth += 1
                i += 2
                continue

        if c == '"':
            in_string = True
            i += 1
            continue

        # Bracket depth tracking
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)

        # ':=' at depth 0
        if (
            depth == 0
            and c == ":"
            and i + 1 < length
            and text[i + 1] == "="
        ):
            return (i, ":=")

        # 'where' at depth 0 (must be a whole word)
        if depth == 0 and i + 4 < length and text[i : i + 5] == "where":
            before_ok = i == 0 or not text[i - 1].isalnum()
            after_pos = i + 5
            after_ok = after_pos >= length or not text[after_pos].isalnum()
            if before_ok and after_ok:
                return (i, "where")

        i += 1

    return None


def parse_lean_source(source: str, file_path: str) -> list[ProofBlock]:
    """Parse Lean 4 source code and extract proof blocks.

    Extracts theorem, lemma, def, instance, and example declarations
    with their signatures and proof bodies.
    """
    lines = source.splitlines()
    comment_lines = _lines_in_block_comments(lines)

    # Step 1: Find all block boundaries and declaration starts
    block_starts: list[tuple[int, tuple[str, ...] | None]] = []

    for i, line in enumerate(lines):
        if i in comment_lines:
            continue
        cls = _classify_line(line)
        if cls is not None:
            block_starts.append((i, cls))

    # Step 2: Extract declaration blocks and parse them
    blocks: list[ProofBlock] = []

    for idx, (start_line, cls) in enumerate(block_starts):
        if cls is None or cls[0] != "decl":
            continue

        kind_str = str(cls[1])
        name = str(cls[2]) if len(cls) > 2 else ""
        kind = _KIND_MAP[kind_str]

        # Find end of block: next boundary or end of file
        end_line = len(lines)
        for next_idx in range(idx + 1, len(block_starts)):
            end_line = block_starts[next_idx][0]
            break

        # Trim trailing blank lines
        while end_line > start_line + 1 and not lines[end_line - 1].strip():
            end_line -= 1

        if end_line <= start_line:
            continue

        block_text = "\n".join(lines[start_line:end_line])

        # Step 3: Split into signature and body
        split = _find_body_split(block_text)
        if split is None:
            # No ':=' or 'where' — pattern match def or forward declaration
            continue

        split_pos, split_type = split

        if split_type == ":=":
            signature = block_text[:split_pos].rstrip()
            body = block_text[split_pos + 2 :].strip()
        else:  # "where"
            signature = block_text[:split_pos].rstrip()
            body = block_text[split_pos:].strip()  # Include 'where' in body

        if not body:
            continue

        blocks.append(
            ProofBlock(
                kind=kind,
                name=name if name else None,
                signature=signature,
                body=body,
                full_text=block_text,
                file_path=file_path,
                start_line=start_line + 1,  # 1-indexed
                end_line=end_line,
            )
        )

    return blocks


def extract_proof_blocks(
    source: str,
    file_path: str,
    *,
    tactic_only: bool = False,
) -> list[ProofBlock]:
    """Extract proof blocks, optionally filtering to tactic proofs only.

    Args:
        source: Lean 4 source code text.
        file_path: Path of the file (for metadata).
        tactic_only: If True, only return blocks with tactic proofs
            (``:= by ...``).
    """
    blocks = parse_lean_source(source, file_path)

    if tactic_only:
        blocks = [b for b in blocks if b.body.lstrip().startswith("by")]

    return blocks
