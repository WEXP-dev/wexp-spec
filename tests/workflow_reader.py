"""A deliberately small reader for the workflow files in this repository.

GitHub Actions workflows decide whether an Internet-Draft can be submitted, so
their trigger and permission structure is asserted by tests. A full YAML parser
is not available in the standard library, and adding a dependency to a
repository whose CI runs on stock Python would be a worse trade than reading
the narrow, self-authored subset used here.

The reader understands exactly one thing: a top-level ``key:`` block and the
keys nested directly inside it. Anything else is left to ``actionlint`` and to
GitHub's own workflow validation.
"""

from __future__ import annotations

import re
from pathlib import Path

TOP_LEVEL_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?P<rest>.*)$")
NESTED_KEY_RE = re.compile(r"^ {2}(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?P<rest>.*)$")
USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<value>\S+)")
PINNED_USES_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def workflow_paths(repo_root: Path) -> list[Path]:
    return sorted((repo_root / ".github" / "workflows").glob("*.yml"))


def _normalize_inline(rest: str) -> list[str]:
    """Rewrite ``on: push`` and ``on: [push, pull_request]`` as nested lines."""

    value = rest.strip()
    if not value or value.startswith("#"):
        return []
    if value.startswith("[") and value.endswith("]"):
        items = [item.strip() for item in value[1:-1].split(",") if item.strip()]
    else:
        items = [value]
    return [f"  {item}:" for item in items]


def top_level_block(text: str, key: str) -> list[str]:
    """Return the lines nested under a top-level ``key:``.

    A line that starts in column zero and is not a comment ends the block.
    """

    lines = text.splitlines()
    collected: list[str] = []
    inside = False
    for line in lines:
        if not inside:
            match = TOP_LEVEL_KEY_RE.match(line)
            if match and match.group("key") == key:
                inside = True
                collected.extend(_normalize_inline(match.group("rest")))
            continue
        if line.strip() and not line.startswith((" ", "\t", "#")):
            break
        collected.append(line)
    if not inside:
        raise KeyError(f"workflow has no top-level {key!r} key")
    return collected


def nested_keys(block: list[str]) -> list[str]:
    """Keys nested exactly one level inside a top-level block."""

    keys: list[str] = []
    for line in block:
        match = NESTED_KEY_RE.match(line)
        if match:
            keys.append(match.group("key"))
    return keys


def triggers(text: str) -> list[str]:
    return nested_keys(top_level_block(text, "on"))


def top_level_permissions(text: str) -> dict[str, str]:
    permissions: dict[str, str] = {}
    for line in top_level_block(text, "permissions"):
        match = NESTED_KEY_RE.match(line)
        if match:
            permissions[match.group("key")] = match.group("rest").strip()
    return permissions


def action_references(text: str) -> list[str]:
    references: list[str] = []
    for line in text.splitlines():
        match = USES_RE.match(line)
        if match:
            references.append(match.group("value"))
    return references


def is_sha_pinned(reference: str) -> bool:
    return bool(PINNED_USES_RE.match(reference))
