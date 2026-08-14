"""Publication guard policy tests.

Each negative test mutates exactly one fact in an otherwise-passing publication
event and asserts that the guard fails closed on the intended check.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402
import publication_guard as guard  # noqa: E402


class GuardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def context(self, **overrides):
        return support.passing_context(self.root, **overrides)

    def assertFailsOn(self, report: guard.GuardReport, check_id: str) -> None:
        failed = {check.check_id for check in report.failures}
        self.assertIn(
            check_id,
            failed,
            msg=f"expected {check_id} to fail; failures were {sorted(failed) or 'none'}",
        )


class TestPositivePath(GuardTestCase):
    def test_fully_authorized_event_passes_every_check(self) -> None:
        report = guard.run_checks(self.context())
        self.assertTrue(report.ok, msg=report.first_failure)
        self.assertEqual(len(report.checks), 14)
        self.assertEqual(
            [check.check_id for check in report.checks],
            [f"G{index:02d}" for index in range(1, 15)],
        )


class TestTriggerChecks(GuardTestCase):
    def test_no_ref_fails_closed(self) -> None:
        self.assertFailsOn(guard.run_checks(self.context(triggering_ref=None)), "G01")

    def test_branch_ref_cannot_publish(self) -> None:
        report = guard.run_checks(self.context(triggering_ref="refs/heads/main"))
        self.assertFailsOn(report, "G01")

    def test_pull_request_ref_cannot_publish(self) -> None:
        report = guard.run_checks(self.context(triggering_ref="refs/pull/7/merge"))
        self.assertFailsOn(report, "G01")

    def test_wrong_tag_fails_closed(self) -> None:
        report = guard.run_checks(self.context(triggering_ref="refs/tags/v1.0.0"))
        self.assertFailsOn(report, "G01")

    def test_tag_for_a_different_revision_fails_closed(self) -> None:
        report = guard.run_checks(self.context(triggering_ref="refs/tags/draft-example-wexp-core-02"))
        self.assertFailsOn(report, "G01")

    def test_stale_ref_not_resolving_to_a_commit_fails_closed(self) -> None:
        self.assertFailsOn(guard.run_checks(self.context(tag_commit=None)), "G02")

    def test_tag_commit_differing_from_checkout_fails_closed(self) -> None:
        report = guard.run_checks(self.context(head_commit="9" * 40))
        self.assertFailsOn(report, "G02")

    def test_commit_outside_authorized_state_fails_closed(self) -> None:
        report = guard.run_checks(self.context(commit_on_authorized_state=False))
        self.assertFailsOn(report, "G03")

    def test_unobserved_authorized_state_fails_closed(self) -> None:
        report = guard.run_checks(
            self.context(authorized_base_commits=(), commit_on_authorized_state=None)
        )
        self.assertFailsOn(report, "G03")

    def test_lightweight_tag_fails_signature_policy(self) -> None:
        report = guard.run_checks(self.context(tag_is_annotated=False, tag_signature_verified=None))
        self.assertFailsOn(report, "G04")

    def test_unverified_signature_fails_closed(self) -> None:
        report = guard.run_checks(self.context(tag_signature_verified=False))
        self.assertFailsOn(report, "G04")

    def test_unobserved_signature_is_not_a_pass(self) -> None:
        report = guard.run_checks(self.context(tag_signature_verified=None))
        self.assertFailsOn(report, "G04")


class TestIdentityChecks(GuardTestCase):
    def test_tag_revision_not_matching_record_revision_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        record["revision"] = "02"
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G05")

    def test_wrong_draft_name_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        record["draft_name"] = "draft-someone-else-wexp-core"
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G08")

    def test_missing_authorized_xml_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        xml_path.unlink()
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G06")

    def test_xml_changed_after_authorization_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        authorization_path = support.write_authorization(self.root, record)
        xml_path.write_text(
            support.MINIMAL_XML.format(identity=identity).replace("Fixture body.", "Edited after authorization."),
            encoding="utf-8",
        )
        report = guard.run_checks(
            self.context(
                authorization=record,
                authorization_path=authorization_path,
                submission_xml_sha256=support.sha256_text(xml_path),
            )
        )
        self.assertFailsOn(report, "G06")

    def test_docname_not_matching_identity_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        body = support.MINIMAL_XML.format(identity="draft-example-wexp-core-00")
        xml_path = support.write_xml(self.root, identity, body=body)
        record = support.authorization_dict(self.root, identity, xml_path)
        report = guard.run_checks(
            self.context(
                authorization=record,
                authorization_path=support.write_authorization(self.root, record),
                submission_xml_sha256=support.sha256_text(xml_path),
            )
        )
        self.assertFailsOn(report, "G07")

    def test_missing_ipr_attribute_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        body = support.MINIMAL_XML.format(identity=identity).replace(' ipr="trust200902"', "")
        xml_path = support.write_xml(self.root, identity, body=body)
        record = support.authorization_dict(self.root, identity, xml_path)
        report = guard.run_checks(
            self.context(
                authorization=record,
                authorization_path=support.write_authorization(self.root, record),
                submission_xml_sha256=support.sha256_text(xml_path),
            )
        )
        self.assertFailsOn(report, "G07")

    def test_cited_internet_draft_references_do_not_break_series_matching(self) -> None:
        # A draft's <back> matter cites other Internet-Drafts, each carrying its
        # own <seriesInfo name="Internet-Draft">. Only the front matter states
        # this document's identity.
        identity = "draft-example-wexp-core-01"
        body = support.MINIMAL_XML.format(identity=identity).replace(
            "<back/>",
            "<back><references><name>References</name>"
            '<reference anchor="OTHER"><front><title>Other</title>'
            '<author fullname="X. Author"/><date year="2026"/></front>'
            '<seriesInfo name="Internet-Draft" value="draft-someone-else-00"/>'
            "</reference></references></back>",
        )
        xml_path = support.write_xml(self.root, identity, body=body)
        record = support.authorization_dict(self.root, identity, xml_path)
        report = guard.run_checks(
            self.context(
                authorization=record,
                authorization_path=support.write_authorization(self.root, record),
                submission_xml_sha256=support.sha256_text(xml_path),
            )
        )
        self.assertNotIn("G07", {check.check_id for check in report.failures})

    def test_front_matter_series_mismatch_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        body = support.MINIMAL_XML.format(identity=identity).replace(
            "<abstract>",
            '<seriesInfo name="Internet-Draft" value="draft-example-wexp-core-00"/><abstract>',
        )
        xml_path = support.write_xml(self.root, identity, body=body)
        record = support.authorization_dict(self.root, identity, xml_path)
        report = guard.run_checks(
            self.context(
                authorization=record,
                authorization_path=support.write_authorization(self.root, record),
                submission_xml_sha256=support.sha256_text(xml_path),
            )
        )
        self.assertFailsOn(report, "G07")

    def test_submission_bundle_differing_from_authorized_xml_fails_closed(self) -> None:
        report = guard.run_checks(self.context(submission_xml_sha256="c" * 64))
        self.assertFailsOn(report, "G14")

    def test_absent_submission_digest_is_not_a_pass(self) -> None:
        self.assertFailsOn(guard.run_checks(self.context(submission_xml_sha256=None)), "G14")


class TestAuthorizationChecks(GuardTestCase):
    def test_missing_authorization_fields_fail_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        del record["authorized_by"]
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G08")

    def test_unsigned_human_identity_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        record["authorized_by"] = {"identity": "   ", "date": "2026-08-14T00:00:00Z"}
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G08")

    def test_historical_import_record_may_never_enable_submission(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        record["record_kind"] = guard.HISTORICAL_IMPORT
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G08")
        self.assertFailsOn(report, "G09")

    def test_wrong_candidate_identity_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        record["publication_candidate"]["candidate_id"] = "candidate-1"
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G09")

    def test_candidate_digest_not_matching_repository_digest_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        record["publication_candidate"]["authorized_xml_sha256"] = "d" * 64
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G14")

    def test_floating_candidate_identity_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        record["publication_candidate"]["source_workspace"] = "workspace@main"
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G09")

    def test_short_candidate_commit_fails_closed(self) -> None:
        identity = "draft-example-wexp-core-01"
        xml_path = support.write_xml(self.root, identity)
        record = support.authorization_dict(self.root, identity, xml_path)
        record["publication_candidate"]["source_commit"] = "abc1234"
        report = guard.run_checks(
            self.context(authorization=record, authorization_path=support.write_authorization(self.root, record))
        )
        self.assertFailsOn(report, "G09")


class TestWorkspaceBuildAndLeakChecks(GuardTestCase):
    def test_dirty_workspace_fails_closed(self) -> None:
        self.assertFailsOn(guard.run_checks(self.context(workspace_clean=False)), "G10")

    def test_unobserved_workspace_state_is_not_a_pass(self) -> None:
        self.assertFailsOn(guard.run_checks(self.context(workspace_clean=None)), "G10")

    def test_missing_build_report_fails_closed(self) -> None:
        self.assertFailsOn(guard.run_checks(self.context(build=None)), "G11")

    def test_failed_render_fails_closed(self) -> None:
        build = guard.BuildReport(True, False, False, True, "PASS")
        self.assertFailsOn(guard.run_checks(self.context(build=build)), "G11")

    def test_lint_errors_fail_closed(self) -> None:
        build = guard.BuildReport(True, True, True, True, "FAIL")
        self.assertFailsOn(guard.run_checks(self.context(build=build)), "G11")

    def test_lint_not_run_fails_closed(self) -> None:
        build = guard.BuildReport(True, True, True, False, "NOT_RUN")
        self.assertFailsOn(guard.run_checks(self.context(build=build)), "G11")

    def test_private_path_reference_fails_closed(self) -> None:
        leak = self.root / "leak.txt"
        leak.write_text("see engineering/core-01/first-slice for details\n", encoding="utf-8")
        report = guard.run_checks(self.context(scan_paths=(leak,)))
        self.assertFailsOn(report, "G12")

    def test_credential_shaped_material_fails_closed(self) -> None:
        leak = self.root / "leak.json"
        leak.write_text('{"token": "ghp_' + "A" * 36 + '"}\n', encoding="utf-8")
        report = guard.run_checks(self.context(scan_paths=(leak,)))
        self.assertFailsOn(report, "G13")

    def test_private_key_block_fails_closed(self) -> None:
        leak = self.root / "key.txt"
        leak.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n", encoding="utf-8")
        report = guard.run_checks(self.context(scan_paths=(leak,)))
        self.assertFailsOn(report, "G13")


class TestRepositoryRecords(unittest.TestCase):
    """The records actually committed to this repository must be well-formed."""

    def test_core_00_record_is_a_non_authorization_that_cannot_submit(self) -> None:
        path = support.REPO_ROOT / "publication" / "authorizations" / "draft-sergeev-wexp-core-00.json"
        record = guard.load_authorization(path)
        self.assertEqual(record["record_kind"], guard.HISTORICAL_IMPORT)
        self.assertFalse(record["submission"]["enabled"])
        self.assertEqual(record["artifact_identity"], "draft-sergeev-wexp-core-00")

    def test_every_committed_record_declares_a_known_kind(self) -> None:
        directory = support.REPO_ROOT / "publication" / "authorizations"
        records = sorted(directory.glob("*.json"))
        self.assertTrue(records, "at least one authorization record must exist")
        for path in records:
            with self.subTest(record=path.name):
                record = guard.load_authorization(path)
                self.assertIn(record.get("record_kind"), guard.RECORD_KINDS)
                self.assertEqual(path.stem, record.get("artifact_identity"))

    def test_committed_authorized_xml_digests_are_current(self) -> None:
        directory = support.REPO_ROOT / "publication" / "authorizations"
        for path in sorted(directory.glob("*.json")):
            record = guard.load_authorization(path)
            authorized = record["authorized_xml"]
            with self.subTest(record=path.name):
                artifact = support.REPO_ROOT / authorized["path"]
                self.assertTrue(artifact.is_file(), f"missing {authorized['path']}")
                self.assertEqual(guard.sha256_file(artifact), authorized["sha256"])


if __name__ == "__main__":
    unittest.main()
