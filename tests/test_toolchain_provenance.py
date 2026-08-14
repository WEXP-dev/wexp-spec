"""Toolchain provenance tests.

The publication pipeline must build its own toolchain from pins this repository
owns. An ambient toolchain is not a cosmetic issue: ``xml2rfc`` embeds the
interpreter version and every installed dependency version into the rendered
HTML, so a borrowed environment silently changes published bytes while still
reporting the same ``xml2rfc`` version.

These tests do not provision anything. They assert that the declaration and the
locks are complete and pinned, and that no tracked file reaches for a toolchain
belonging to someone else's machine or project.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402

TOOLS = support.REPO_ROOT / "tools"
DECLARATION = TOOLS / "toolchain.json"
PYTHON_LOCK = TOOLS / "python-toolchain.lock"
NODE_LOCK = TOOLS / "node" / "package-lock.json"
NODE_MANIFEST = TOOLS / "node" / "package.json"

EXACT_PIN_RE = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>[A-Za-z0-9._+!-]+)\s*\\?$")
HASH_RE = re.compile(r"^\s+--hash=sha256:[0-9a-f]{64}\s*\\?$")

#: Ways a file could reach for a toolchain this repository does not own.
FOREIGN_TOOLCHAIN_PATTERNS = (
    ("private project toolchain", re.compile(r"\.tools/bin")),
    ("home-directory tool path", re.compile(r"\$HOME/[A-Za-z]")),
    ("home-relative toolchain", re.compile(r"~/[A-Za-z0-9_-]+/\.tools")),
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(support.REPO_ROOT), "ls-files"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    if result.returncode == 0 and result.stdout.strip():
        return [support.REPO_ROOT / line for line in result.stdout.split()]
    return [
        path
        for path in support.REPO_ROOT.rglob("*")
        if path.is_file() and ".git" not in path.parts and "build" not in path.parts
    ]


class TestDeclaration(unittest.TestCase):
    def setUp(self) -> None:
        self.declaration = json.loads(DECLARATION.read_text(encoding="utf-8"))

    def test_every_python_package_is_exactly_pinned(self) -> None:
        packages = self.declaration["python_packages"]
        self.assertTrue(packages)
        for name, version in packages.items():
            with self.subTest(package=name):
                self.assertRegex(version, r"^[0-9][A-Za-z0-9._+!-]*$", "version must be exact")

    def test_the_direct_requirement_is_present_in_the_resolved_set(self) -> None:
        for requirement in self.declaration["direct_python_requirements"]:
            name, _, version = requirement.partition("==")
            with self.subTest(requirement=requirement):
                self.assertEqual(self.declaration["python_packages"].get(name), version)

    def test_the_interpreter_is_pinned_to_a_major_minor(self) -> None:
        self.assertRegex(str(self.declaration["interpreter"]["version"]), r"^3\.\d+$")

    def test_provenance_records_where_the_pins_came_from(self) -> None:
        provenance = self.declaration["provenance"]
        self.assertEqual(provenance["python_index"], "https://pypi.org")
        self.assertEqual(provenance["node_registry"], "https://registry.npmjs.org")
        self.assertTrue(provenance["resolved_on"])
        self.assertTrue(provenance["resolution_note"])


class TestPythonLock(unittest.TestCase):
    def setUp(self) -> None:
        self.declaration = json.loads(DECLARATION.read_text(encoding="utf-8"))
        self.lines = [
            line
            for line in PYTHON_LOCK.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_every_line_is_either_an_exact_pin_or_a_sha256_hash(self) -> None:
        for line in self.lines:
            with self.subTest(line=line[:60]):
                self.assertTrue(
                    EXACT_PIN_RE.match(line) or HASH_RE.match(line),
                    msg="lock lines must be exact pins or sha256 hashes",
                )

    def test_every_declared_package_is_locked_with_at_least_one_hash(self) -> None:
        locked: dict[str, int] = {}
        current: str | None = None
        for line in self.lines:
            pin = EXACT_PIN_RE.match(line)
            if pin:
                current = pin.group("name").lower().replace("_", "-")
                locked[current] = 0
            elif current and HASH_RE.match(line):
                locked[current] += 1

        declared = {name.lower().replace("_", "-") for name in self.declaration["python_packages"]}
        self.assertEqual(set(locked), declared, "lock and declaration must cover the same packages")
        for name, count in locked.items():
            with self.subTest(package=name):
                self.assertGreater(count, 0, "pip --require-hashes needs at least one hash")

    def test_locked_versions_match_the_declaration(self) -> None:
        declared = {
            name.lower().replace("_", "-"): version
            for name, version in self.declaration["python_packages"].items()
        }
        for line in self.lines:
            pin = EXACT_PIN_RE.match(line)
            if pin:
                name = pin.group("name").lower().replace("_", "-")
                with self.subTest(package=name):
                    self.assertEqual(pin.group("version"), declared[name])


class TestNodeLock(unittest.TestCase):
    def setUp(self) -> None:
        self.declaration = json.loads(DECLARATION.read_text(encoding="utf-8"))
        self.lock = json.loads(NODE_LOCK.read_text(encoding="utf-8"))

    def test_the_linter_version_and_integrity_match_the_declaration(self) -> None:
        declared = self.declaration["node"]
        entry = self.lock["packages"][f"node_modules/{declared['package']}"]
        self.assertEqual(entry["version"], declared["version"])
        self.assertEqual(entry["integrity"], declared["integrity"])

    def test_the_manifest_pins_an_exact_version(self) -> None:
        manifest = json.loads(NODE_MANIFEST.read_text(encoding="utf-8"))
        declared = self.declaration["node"]
        self.assertEqual(manifest["dependencies"][declared["package"]], declared["version"])

    def test_every_locked_package_carries_an_integrity_digest(self) -> None:
        for name, entry in self.lock["packages"].items():
            if not name or entry.get("link"):
                continue
            with self.subTest(package=name):
                self.assertIn("integrity", entry)


class TestNoForeignToolchainDependency(unittest.TestCase):
    """The regression guard for this repository's toolchain independence."""

    def test_no_tracked_file_reaches_for_a_foreign_toolchain(self) -> None:
        offenders: list[str] = []
        for path in tracked_files():
            if not path.is_file() or path.suffix.lower() in {".html", ".txt", ".xml"}:
                # Published draft artifacts are bytes from the IETF archive and
                # are never edited here; they are covered by manifest hashes.
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for label, pattern in FOREIGN_TOOLCHAIN_PATTERNS:
                if pattern.search(text):
                    offenders.append(f"{path.relative_to(support.REPO_ROOT)}: {label}")
        self.assertEqual(offenders, [], msg="; ".join(offenders))

    def test_no_workflow_prepends_an_unprovisioned_directory_to_path(self) -> None:
        workflows = sorted((support.REPO_ROOT / ".github" / "workflows").glob("*.yml"))
        for path in workflows:
            text = path.read_text(encoding="utf-8")
            # Shell continuations split one command across several YAML lines,
            # so scan logical statements rather than physical lines.
            for line in text.replace("\\\n", " ").splitlines():
                if "GITHUB_PATH" in line or "PATH=" in line:
                    with self.subTest(workflow=path.name, line=line.strip()[:70]):
                        self.assertIn(
                            "TOOLCHAIN.json",
                            line,
                            msg="only the provisioned toolchain may be added to PATH",
                        )

    def test_every_workflow_that_renders_provisions_the_toolchain_first(self) -> None:
        workflows = sorted((support.REPO_ROOT / ".github" / "workflows").glob("*.yml"))
        for path in workflows:
            text = path.read_text(encoding="utf-8")
            if "prepare_publication.py" not in text:
                continue
            with self.subTest(workflow=path.name):
                self.assertIn("scripts/provision_toolchain.py", text)
                self.assertNotIn("pip install", text)
                self.assertNotIn("npm install", text)


if __name__ == "__main__":
    unittest.main()
