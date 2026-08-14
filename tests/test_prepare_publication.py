"""Phase-A tests.

Includes the Core-00 compatibility exercise required of this pipeline: the
already-published historical import must flow through identity resolution,
bundle construction, guard evaluation and request construction, and must
terminate without any possibility of submission.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402
import prepare_publication as prepare_module  # noqa: E402
import publication_guard as guard  # noqa: E402

CORE_00 = "draft-sergeev-wexp-core-00"


class TestIdnitsClassification(unittest.TestCase):
    def test_errors_block(self) -> None:
        payload = {
            "nitsBySeverity": {"error": 1, "warning": 0},
            "nits": [{"severity": "ValidationError", "code": "X", "desc": "bad"}],
        }
        status, messages = prepare_module.classify_idnits(payload)
        self.assertEqual(status, "FAIL")
        self.assertTrue(messages)

    def test_warnings_do_not_block_but_are_recorded(self) -> None:
        status, messages = prepare_module.classify_idnits({"nitsBySeverity": {"error": 0, "warning": 81}})
        self.assertEqual(status, "PASS_WITH_WARNINGS")
        self.assertIn("81 warning(s)", messages[0])

    def test_clean_report_passes(self) -> None:
        status, messages = prepare_module.classify_idnits({"nitsBySeverity": {"error": 0, "warning": 0}})
        self.assertEqual(status, "PASS")
        self.assertEqual(messages, [])

    def test_result_field_alone_is_not_trusted(self) -> None:
        # idnits reports result "fail" for warning-only documents and exits 0 in
        # both cases, so neither field alone may be used as the gate.
        payload = {"result": "fail", "nitsBySeverity": {"error": 0, "warning": 3}}
        self.assertEqual(prepare_module.classify_idnits(payload)[0], "PASS_WITH_WARNINGS")


class TestDiff(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_absent_previous_revision_is_reported_honestly(self) -> None:
        target = self.root / "diff" / "d.diff"
        note = prepare_module.render_diff(None, None, target, "draft-x-01")
        self.assertIn("unavailable", note)
        self.assertIn("no previous published revision", target.read_text(encoding="utf-8"))

    def test_diff_is_written_when_both_sides_exist(self) -> None:
        previous = self.root / "old.txt"
        current = self.root / "new.txt"
        previous.write_text("alpha\nbeta\n", encoding="utf-8")
        current.write_text("alpha\ngamma\n", encoding="utf-8")
        target = self.root / "diff" / "d.diff"
        note = prepare_module.render_diff(previous, current, target, "draft-x-01")
        self.assertIn("unified diff", note)
        self.assertIn("-beta", target.read_text(encoding="utf-8"))

    def test_previous_revision_lookup_skips_revision_00(self) -> None:
        self.assertIsNone(
            prepare_module.previous_revision_text(self.root, {"revision": "00", "draft_name": "draft-x"})
        )


class TestCore00Compatibility(unittest.TestCase):
    """Core-00 exercises the real path and must never become submittable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.bundle_root = Path(cls._tmp.name) / "bundle"
        authorization = support.REPO_ROOT / "publication" / "authorizations" / f"{CORE_00}.json"
        cls.terminal, cls.manifest = prepare_module.prepare(
            support.REPO_ROOT,
            authorization,
            triggering_ref=f"refs/tags/{CORE_00}",
            bundle_root=cls.bundle_root,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_the_pipeline_recognises_the_existing_draft_identity(self) -> None:
        self.assertEqual(self.manifest["artifact_identity"], CORE_00)
        self.assertEqual(self.manifest["authorization"]["authorization_id"], "PA-core-00-import-001")

    def test_a_bundle_is_constructed(self) -> None:
        for relative in ("BUNDLE-MANIFEST.json", "SHA256SUMS", "RESULT.txt"):
            with self.subTest(artifact=relative):
                self.assertTrue((self.bundle_root / relative).is_file())
        for relative in ("evidence/guard-report.json", "evidence/dry-run.json", "evidence/build-report.json"):
            with self.subTest(artifact=relative):
                self.assertTrue((self.bundle_root / relative).is_file())

    def test_the_bundled_xml_is_byte_identical_to_the_published_import(self) -> None:
        bundled = self.bundle_root / "submission" / f"{CORE_00}.xml"
        published = support.REPO_ROOT / "drafts" / "core" / "00" / f"{CORE_00}.xml"
        self.assertEqual(bundled.read_bytes(), published.read_bytes())
        self.assertEqual(
            self.manifest["submission_xml"]["sha256"],
            "6cd8b680059cc81e1ec4c84737d9319ee242ef63e89c57de497bd57ede08d810",
        )

    def test_it_terminates_not_ready_because_submission_is_unauthorized(self) -> None:
        self.assertTrue(self.terminal.startswith("NOT READY —"), msg=self.terminal)
        self.assertIn("submission is not authorized", self.terminal)

    def test_no_submission_was_performed(self) -> None:
        dry_run = json.loads((self.bundle_root / "evidence" / "dry-run.json").read_text(encoding="utf-8"))
        self.assertEqual(dry_run["result"], "SUBMISSION NOT PERFORMED")
        self.assertFalse(dry_run["network_submission_performed"])
        self.assertFalse(self.manifest["submission_performed"])
        self.assertIn("SUBMISSION NOT PERFORMED", (self.bundle_root / "RESULT.txt").read_text(encoding="utf-8"))

    def test_the_request_preview_is_built_and_redacted(self) -> None:
        preview = json.loads(
            (self.bundle_root / "evidence" / "submission-request-preview.json").read_text(encoding="utf-8")
        )
        self.assertEqual(preview["url"], "https://datatracker.ietf.org/api/submission")
        self.assertEqual(preview["method"], "POST")
        self.assertFalse(preview["submission_authorized"])

    def test_sha256sums_covers_every_bundle_file(self) -> None:
        listed = {
            line.split("  ", 1)[1]
            for line in (self.bundle_root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        present = {
            path.relative_to(self.bundle_root).as_posix()
            for path in self.bundle_root.rglob("*")
            if path.is_file() and path.name not in {"SHA256SUMS", "RESULT.txt"}
        }
        self.assertEqual(listed, present)


class TestPositiveDryRunFixture(unittest.TestCase):
    """A synthetic revision for which everything passes still does not submit."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.identity = "draft-example-wexp-core-01"
        self.xml = support.write_xml(self.root, self.identity)
        record = support.authorization_dict(self.root, self.identity, self.xml)
        self.authorization = support.write_authorization(self.root, record)

        def fake_build(xml_path: Path, output_dir: Path, identity: str):
            output_dir.mkdir(parents=True, exist_ok=True)
            text_path = output_dir / f"{identity}.txt"
            html_path = output_dir / f"{identity}.html"
            text_path.write_text("rendered fixture\n", encoding="utf-8")
            html_path.write_text("<html><body>fixture</body></html>\n", encoding="utf-8")
            return prepare_module.BuildOutcome(
                report=support.passing_build(), text_path=text_path, html_path=html_path, lint_path=None
            )

        original_build = prepare_module.build_draft
        original_facts = guard.collect_git_facts
        prepare_module.build_draft = fake_build
        guard.collect_git_facts = lambda repo_root, tag: {
            "head_commit": support.DUMMY_COMMIT,
            "tag_commit": support.DUMMY_COMMIT,
            "tag_is_annotated": True,
            "tag_signature_verified": True,
            "workspace_clean": True,
            "authorized_base_commits": (support.DUMMY_BASE_COMMIT,),
            "commit_on_authorized_state": True,
        }
        self.addCleanup(setattr, prepare_module, "build_draft", original_build)
        self.addCleanup(setattr, guard, "collect_git_facts", original_facts)

    def test_ready_verdict_still_performs_no_submission(self) -> None:
        terminal, manifest = prepare_module.prepare(
            self.root,
            self.authorization,
            triggering_ref=f"refs/tags/{self.identity}",
            bundle_root=self.root / "bundle",
        )
        self.assertEqual(terminal, "READY FOR IETF SUBMISSION", msg=terminal)
        self.assertEqual(manifest["guard"]["result"], "PASS")
        self.assertFalse(manifest["submission_performed"])
        self.assertEqual(manifest["dry_run"]["result"], "SUBMISSION NOT PERFORMED")
        self.assertTrue(manifest["submission_metadata_preview"]["submission_authorized"])

    def test_disabled_submission_blocks_even_when_the_guard_passes(self) -> None:
        record = guard.load_authorization(self.authorization)
        record["submission"]["enabled"] = False
        record["submission"]["reason"] = "held pending human authorization"
        self.authorization.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        terminal, manifest = prepare_module.prepare(
            self.root,
            self.authorization,
            triggering_ref=f"refs/tags/{self.identity}",
            bundle_root=self.root / "bundle",
        )
        self.assertIn("held pending human authorization", terminal)
        self.assertTrue(terminal.startswith("NOT READY —"))
        self.assertFalse(manifest["submission_performed"])


class TestAuthorizationResolution(unittest.TestCase):
    def test_unknown_identity_is_refused(self) -> None:
        with self.assertRaises(guard.GuardError):
            prepare_module.resolve_authorization(support.REPO_ROOT, "draft-does-not-exist-00", None)

    def test_known_identity_resolves(self) -> None:
        resolved = prepare_module.resolve_authorization(support.REPO_ROOT, CORE_00, None)
        self.assertTrue(resolved.is_file())


if __name__ == "__main__":
    unittest.main()
