"""Workflow trigger and permission tests.

These are the structural half of the "no accidental submission" property: the
guard decides whether a *requested* publication is legitimate, while these
tests decide which events can request one at all.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402
import workflow_reader as reader  # noqa: E402

SUBMIT_WORKFLOW = "ietf-publication-submit.yml"
PREPARE_WORKFLOW = "ietf-publication-prepare.yml"

#: Anything that could lead to a live submission.
SUBMISSION_MARKERS = ("submit_publication.py", "WEXP_DATATRACKER_SUBMIT", "--live")


class WorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.paths = reader.workflow_paths(support.REPO_ROOT)
        self.assertTrue(self.paths, "the repository must define workflows")
        self.texts = {path.name: path.read_text(encoding="utf-8") for path in self.paths}


class TestNoAccidentalSubmission(WorkflowTestCase):
    def test_ordinary_push_and_pull_request_workflows_cannot_submit(self) -> None:
        for name, text in self.texts.items():
            if name == SUBMIT_WORKFLOW:
                continue
            with self.subTest(workflow=name):
                for marker in SUBMISSION_MARKERS:
                    self.assertNotIn(
                        marker,
                        text,
                        msg=f"{name} references {marker!r} and could reach a submission",
                    )

    def test_submit_workflow_is_manual_dispatch_only(self) -> None:
        self.assertEqual(reader.triggers(self.texts[SUBMIT_WORKFLOW]), ["workflow_dispatch"])

    def test_prepare_workflow_never_runs_on_branches_or_pull_requests(self) -> None:
        text = self.texts[PREPARE_WORKFLOW]
        self.assertEqual(sorted(reader.triggers(text)), ["push", "workflow_dispatch"])
        push_block = "\n".join(reader.top_level_block(text, "on"))
        self.assertIn("tags:", push_block)
        self.assertNotIn("branches:", push_block)

    def test_no_workflow_uses_pull_request_target(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertNotIn("pull_request_target", text)

    def test_no_workflow_is_triggered_by_a_release(self) -> None:
        # A GitHub release is easy to create by accident and is the trigger the
        # common community template uses. This repository deliberately does not.
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertNotIn("release:", "\n".join(reader.top_level_block(text, "on")))


class TestSubmitWorkflowIsHardDisabled(WorkflowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.text = self.texts[SUBMIT_WORKFLOW]

    def test_it_requires_an_unset_repository_variable(self) -> None:
        self.assertIn("vars.WEXP_PUBLICATION_ENABLED", self.text)
        self.assertIn('!= "true"', self.text)

    def test_it_refuses_to_run_outside_the_canonical_repository(self) -> None:
        self.assertIn('!= "WEXP-dev/wexp-spec"', self.text)

    def test_it_requires_a_protected_environment(self) -> None:
        self.assertIn("environment: ietf-publication", self.text)

    def test_it_requires_typed_confirmation_and_an_expected_digest(self) -> None:
        for required_input in ("confirm_identity", "expected_xml_sha256", "identity", "ref"):
            with self.subTest(input=required_input):
                self.assertIn(f"{required_input}:", self.text)

    def test_the_submit_job_depends_on_the_gate_job(self) -> None:
        self.assertIn("needs: gate", self.text)


class TestLeastPrivilege(WorkflowTestCase):
    def test_every_workflow_declares_read_only_top_level_permissions(self) -> None:
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertEqual(reader.top_level_permissions(text), {"contents": "read"})

    def test_no_workflow_references_a_repository_secret(self) -> None:
        # The Datatracker submission interface takes no credential, so no
        # workflow has any reason to touch secrets. An untrusted fork pull
        # request therefore has nothing to capture.
        for name, text in self.texts.items():
            with self.subTest(workflow=name):
                self.assertNotIn("secrets.", text)

    def test_every_action_is_pinned_to_an_immutable_commit(self) -> None:
        for name, text in self.texts.items():
            for reference in reader.action_references(text):
                with self.subTest(workflow=name, action=reference):
                    self.assertTrue(
                        reader.is_sha_pinned(reference),
                        msg=f"{reference} is not pinned to a 40-character commit SHA",
                    )

    def test_publication_workflows_do_not_persist_git_credentials(self) -> None:
        for name in (PREPARE_WORKFLOW, SUBMIT_WORKFLOW):
            with self.subTest(workflow=name):
                self.assertIn("persist-credentials: false", self.texts[name])


class TestWorkflowReader(unittest.TestCase):
    def test_missing_key_is_an_error_rather_than_an_empty_block(self) -> None:
        with self.assertRaises(KeyError):
            reader.top_level_block("name: x\n", "permissions")

    def test_inline_value_is_captured(self) -> None:
        self.assertEqual(reader.nested_keys(reader.top_level_block("on: push\n", "on")), ["push"])

    def test_block_ends_at_the_next_top_level_key(self) -> None:
        text = "on:\n  push:\n    branches: [main]\njobs:\n  build:\n"
        self.assertEqual(reader.triggers(text), ["push"])

    def test_unpinned_reference_is_rejected(self) -> None:
        self.assertFalse(reader.is_sha_pinned("actions/checkout@v4"))
        self.assertTrue(reader.is_sha_pinned("actions/checkout@" + "a" * 40))


if __name__ == "__main__":
    unittest.main()
