"""Signature-requirement invariant.

    A repository workflow used for WEXP publication MUST NOT disable required
    tag signature verification, through ``--no-require-signature`` or an
    equivalent bypass, unless a future explicit human governance change
    authorises that behaviour.

``publication_guard`` deliberately exposes a way to rehearse an unsigned ref
locally. That escape hatch is load-bearing: with it, an unannotated tag passes
G04. Nothing else in the repository prevents a future workflow edit from
switching it on, so the invariant is asserted here rather than left to review.

These tests inspect the arguments a workflow would actually pass, not merely
the text of the file, and they derive the inventory of bypasses from the
scripts themselves so that a newly added one fails loudly instead of slipping
through unnoticed.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402
import workflow_reader as reader  # noqa: E402
import publication_guard as guard  # noqa: E402

SCRIPTS = support.REPO_ROOT / "scripts"

#: Scripts that evaluate the publication guard and therefore expose the policy.
PUBLICATION_SCRIPTS = ("publication_guard.py", "prepare_publication.py", "submit_publication.py")

#: The bypasses known to exist and reviewed as acceptable for local rehearsal.
KNOWN_BYPASS_FLAGS = frozenset({"--no-require-signature"})

#: Programmatic equivalents of the flags above.
PROGRAMMATIC_BYPASS_RE = re.compile(r"require_tag_signature\s*=\s*False|require_signature\s*=\s*False")

#: Any argparse flag on a publication script that turns a requirement off.
DECLARED_NEGATIVE_FLAG_RE = re.compile(r'add_argument\(\s*\n?\s*"(?P<flag>--no-[a-z0-9-]+)"')


def publication_script_flags() -> set[str]:
    """Every ``--no-*`` argparse flag declared by a publication script."""

    flags: set[str] = set()
    for name in PUBLICATION_SCRIPTS:
        source = (SCRIPTS / name).read_text(encoding="utf-8")
        flags.update(match.group("flag") for match in DECLARED_NEGATIVE_FLAG_RE.finditer(source))
    return flags


def workflow_texts() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in reader.workflow_paths(support.REPO_ROOT)}


class TestSignatureRequirementIsEnforcedByDefault(unittest.TestCase):
    """The invariant is only meaningful if the default is secure."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_guard_context_requires_a_signature_by_default(self) -> None:
        context = guard.GuardContext(
            repo_root=self.root,
            authorization={},
            authorization_path=self.root / "absent.json",
        )
        self.assertTrue(context.require_tag_signature)

    def test_build_context_requires_a_signature_by_default(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        path = support.write_authorization(self.root, record)
        context = guard.build_context(self.root, path, triggering_ref=f"refs/tags/{identity}")
        self.assertTrue(context.require_tag_signature)

    def test_an_unsigned_tag_fails_when_the_requirement_is_on(self) -> None:
        context = support.passing_context(
            self.root, tag_is_annotated=False, tag_signature_verified=None
        )
        report = guard.run_checks(context)
        self.assertIn("G04", {check.check_id for check in report.failures})

    def test_the_bypass_actually_changes_the_verdict(self) -> None:
        # If disabling the requirement made no difference, the workflow
        # invariant below would be vacuous. It does make a difference.
        context = support.passing_context(
            self.root,
            tag_is_annotated=False,
            tag_signature_verified=None,
            require_tag_signature=False,
        )
        report = guard.run_checks(context)
        self.assertNotIn("G04", {check.check_id for check in report.failures})


class TestNoWorkflowDisablesTheSignatureRequirement(unittest.TestCase):
    def test_no_workflow_passes_a_bypass_flag_to_a_publication_script(self) -> None:
        offenders: list[str] = []
        inspected = 0
        for name, text in workflow_texts().items():
            for block in reader.run_blocks(text):
                for command in reader.shell_commands(block):
                    if not any(token.endswith(script) for token in command for script in PUBLICATION_SCRIPTS):
                        continue
                    inspected += 1
                    for token in command:
                        # Compare parsed argv tokens, so a flag hidden by line
                        # continuations or odd spacing is still caught.
                        if token in publication_script_flags() | KNOWN_BYPASS_FLAGS:
                            offenders.append(f"{name}: {' '.join(command)}")
        self.assertEqual(offenders, [], msg="; ".join(offenders))
        self.assertGreater(inspected, 0, "no publication-script invocation was found to inspect")

    def test_no_workflow_disables_the_requirement_programmatically(self) -> None:
        offenders: list[str] = []
        for name, text in workflow_texts().items():
            for body in reader.heredoc_bodies(text):
                if PROGRAMMATIC_BYPASS_RE.search(body):
                    offenders.append(f"{name}: inline program disables the signature requirement")
            for block in reader.run_blocks(text):
                shell, _ = reader.split_heredocs(block)
                if PROGRAMMATIC_BYPASS_RE.search(shell):
                    offenders.append(f"{name}: shell text disables the signature requirement")
        self.assertEqual(offenders, [], msg="; ".join(offenders))

    def test_no_workflow_sets_the_requirement_off_through_an_environment_variable(self) -> None:
        # The current implementation has no environment-variable bypass. This
        # asserts that none appears without the inventory test below noticing.
        for name, text in workflow_texts().items():
            with self.subTest(workflow=name):
                self.assertNotIn("REQUIRE_SIGNATURE", text.upper().replace("NO-REQUIRE-SIGNATURE", ""))


class TestBypassInventoryIsDerivedNotAssumed(unittest.TestCase):
    """A new bypass must fail this test rather than silently widen the surface."""

    def test_the_declared_bypass_flags_are_exactly_the_reviewed_set(self) -> None:
        declared = publication_script_flags()
        self.assertEqual(
            declared,
            set(KNOWN_BYPASS_FLAGS),
            msg=(
                "a publication script declares a --no-* flag that has not been reviewed "
                "against the signature invariant; add it to KNOWN_BYPASS_FLAGS only after "
                "confirming it cannot weaken tag signature verification"
            ),
        )

    def test_only_the_guard_and_prepare_expose_the_policy_knob(self) -> None:
        exposing = sorted(
            path.name
            for path in SCRIPTS.glob("*.py")
            if "require_tag_signature" in path.read_text(encoding="utf-8")
        )
        self.assertEqual(exposing, ["prepare_publication.py", "publication_guard.py"])


class TestWorkflowCommandExtraction(unittest.TestCase):
    """The extraction must be trustworthy for the invariant above to mean anything."""

    def test_line_continuations_are_joined_before_tokenising(self) -> None:
        block = 'python3 scripts/prepare_publication.py \\\n  --identity x \\\n  --no-require-signature\n'
        commands = reader.shell_commands(block)
        self.assertEqual(len(commands), 1)
        self.assertIn("--no-require-signature", commands[0])

    def test_heredoc_bodies_are_not_tokenised_as_shell_words(self) -> None:
        block = "python3 - <<'PY'\nprint(\"it's fine\")\nPY\necho done\n"
        shell, documents = reader.split_heredocs(block)
        self.assertIn("print(\"it's fine\")", documents[0])
        self.assertNotIn("it's fine", shell)
        self.assertIn(["echo", "done"], reader.shell_commands(block))

    def test_inline_and_block_run_steps_are_both_found(self) -> None:
        text = "jobs:\n  a:\n    steps:\n      - run: echo one\n      - run: |\n          echo two\n          echo three\n"
        blocks = reader.run_blocks(text)
        self.assertEqual(len(blocks), 2)
        self.assertIn("echo one", blocks[0])
        self.assertIn("echo three", blocks[1])

    def test_commands_are_separated_on_shell_operators(self) -> None:
        commands = reader.shell_commands("set -e && python3 scripts/publication_guard.py --json out\n")
        self.assertIn(["python3", "scripts/publication_guard.py", "--json", "out"], commands)


if __name__ == "__main__":
    unittest.main()
