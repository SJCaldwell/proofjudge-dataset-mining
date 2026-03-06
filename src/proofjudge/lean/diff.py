"""Unified diff parsing for fallback proof extraction.

When full file content cannot be fetched at a given commit SHA,
this module provides utilities to extract changed proof regions
from unified diff hunks (e.g., from review comment diff_hunk fields).
"""

import logging
import re

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Pattern matching unified diff hunk headers
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# Pattern to identify declaration names in diff context
_DECL_NAME_PATTERN = re.compile(
    r"(?:theorem|lemma|def|instance)\s+(\w[\w'.]*)"
)


class DiffHunk(BaseModel):
    """A single hunk from a unified diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    old_lines: list[str]
    new_lines: list[str]
    context_lines: list[str]


def parse_diff_hunks(diff_text: str) -> list[DiffHunk]:
    """Parse unified diff text into individual hunks.

    Handles the standard unified diff format with ``@@`` hunk headers
    and ``-``/``+``/`` `` line prefixes.
    """
    hunks: list[DiffHunk] = []
    current: DiffHunk | None = None

    for line in diff_text.split("\n"):
        match = _HUNK_HEADER.match(line)
        if match:
            if current is not None:
                hunks.append(current)
            current = DiffHunk(
                old_start=int(match.group(1)),
                old_count=int(match.group(2) or "1"),
                new_start=int(match.group(3)),
                new_count=int(match.group(4) or "1"),
                old_lines=[],
                new_lines=[],
                context_lines=[],
            )
            continue

        if current is None:
            continue

        if line.startswith("-"):
            current.old_lines.append(line[1:])
        elif line.startswith("+"):
            current.new_lines.append(line[1:])
        elif line.startswith(" "):
            content = line[1:]
            current.context_lines.append(content)
            current.old_lines.append(content)
            current.new_lines.append(content)

    if current is not None:
        hunks.append(current)

    return hunks


def find_declaration_in_hunk(hunk: DiffHunk) -> str | None:
    """Try to find a declaration name in a diff hunk.

    Searches context lines first (most reliable), then old/new lines.
    Returns the declaration name or ``None``.
    """
    for line in hunk.context_lines:
        match = _DECL_NAME_PATTERN.search(line)
        if match:
            return match.group(1)

    for line in hunk.old_lines + hunk.new_lines:
        match = _DECL_NAME_PATTERN.search(line)
        if match:
            return match.group(1)

    return None


def find_declarations_in_diff(diff_text: str) -> list[str]:
    """Extract all declaration names mentioned in a unified diff.

    Returns a deduplicated list of declaration names found across all hunks.
    """
    hunks = parse_diff_hunks(diff_text)
    names: list[str] = []
    seen: set[str] = set()

    for hunk in hunks:
        name = find_declaration_in_hunk(hunk)
        if name is not None and name not in seen:
            names.append(name)
            seen.add(name)

    return names
