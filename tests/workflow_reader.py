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
import shlex
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


# A run step may be written as ``run:`` under a named step, or inline as a
# list item ``- run:``. Both must be found: missing the second form would
# leave a way to invoke a publication script unchecked.
RUN_BLOCK_RE = re.compile(r"^(?P<prefix>\s*(?:-\s+)?)run:\s*(?P<inline>.*)$")
HEREDOC_RE = re.compile(r"<<-?\s*(?P<quote>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)")
COMMAND_SEPARATORS = re.compile(r"(?:\|\||&&|[;|\n])")


def run_blocks(text: str) -> list[str]:
    """Return the body of every ``run:`` step in a workflow.

    Both the inline form (``run: something``) and the block form
    (``run: |`` followed by an indented body) are returned as plain shell text.
    """

    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        match = RUN_BLOCK_RE.match(lines[index])
        if not match:
            index += 1
            continue
        inline = match.group("inline").strip()
        indent = len(match.group("prefix"))
        index += 1
        if inline and inline not in {"|", ">", "|-", ">-"}:
            blocks.append(inline)
            continue
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            body.append(line)
            index += 1
        blocks.append("\n".join(body))
    return blocks


def split_heredocs(block: str) -> tuple[str, list[str]]:
    """Separate heredoc bodies from the shell text that surrounds them.

    Heredoc bodies are inline programs, not shell words. Splitting them out
    keeps shell tokenisation honest and lets callers inspect the embedded
    program separately.
    """

    lines = block.splitlines()
    shell: list[str] = []
    documents: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = HEREDOC_RE.search(line)
        shell.append(line)
        index += 1
        if not match:
            continue
        tag = match.group("tag")
        body: list[str] = []
        while index < len(lines) and lines[index].strip() != tag:
            body.append(lines[index])
            index += 1
        index += 1  # consume the terminator
        documents.append("\n".join(body))
    return "\n".join(shell), documents


def shell_commands(block: str) -> list[list[str]]:
    """Tokenise a ``run:`` body into argv-style commands.

    Line continuations are joined first, so a command split across several YAML
    lines is inspected as the single command the shell would execute.
    """

    shell, _ = split_heredocs(block)
    joined = shell.replace("\\\n", " ")
    commands: list[list[str]] = []
    for fragment in COMMAND_SEPARATORS.split(joined):
        fragment = fragment.strip()
        if not fragment or fragment.startswith("#"):
            continue
        try:
            tokens = shlex.split(fragment, comments=True)
        except ValueError:
            tokens = fragment.split()
        if tokens:
            commands.append(tokens)
    return commands


def heredoc_bodies(text: str) -> list[str]:
    """Every inline program embedded in a workflow's ``run:`` steps."""

    documents: list[str] = []
    for block in run_blocks(text):
        documents.extend(split_heredocs(block)[1])
    return documents
