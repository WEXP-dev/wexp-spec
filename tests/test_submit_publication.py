"""Phase-B gate tests.

Nothing here can transmit: the live switch is never armed in these tests, and
the gate logic is exercised as a pure function.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402
import datatracker_submit as dts  # noqa: E402
import publication_guard as guard  # noqa: E402
import submit_publication as phase_b  # noqa: E402

IDENTITY = "draft-example-wexp-core-01"
DIGEST = "e" * 64


def ready_manifest(**overrides) -> dict:
    manifest = {
        "artifact_identity": IDENTITY,
        "terminal_result": "READY FOR IETF SUBMISSION",
        "guard": {"result": "PASS"},
        "submission_xml": {"path": f"submission/{IDENTITY}.xml", "sha256": DIGEST},
    }
    manifest.update(overrides)
    return manifest


def enabling_authorization(**overrides) -> dict:
    record = {
        "record_kind": guard.PUBLICATION_AUTHORIZATION,
        "artifact_identity": IDENTITY,
        "authorization_id": "PA-core-01-001",
        "submission": {"enabled": True, "datatracker_user": "author@example.com"},
    }
    record.update(overrides)
    return record


class TestGateReasons(unittest.TestCase):
    def test_a_fully_ready_bundle_has_no_gate_reasons(self) -> None:
        reasons = phase_b.gate_reasons(
            ready_manifest(), enabling_authorization(), expected_xml_sha256=DIGEST
        )
        self.assertEqual(reasons, [])

    def test_not_ready_bundle_is_blocked(self) -> None:
        manifest = ready_manifest(terminal_result="NOT READY — something")
        reasons = phase_b.gate_reasons(manifest, enabling_authorization(), expected_xml_sha256=DIGEST)
        self.assertIn("bundle terminal result is 'NOT READY — something'", reasons)

    def test_failed_guard_is_blocked(self) -> None:
        manifest = ready_manifest(guard={"result": "FAIL"})
        reasons = phase_b.gate_reasons(manifest, enabling_authorization(), expected_xml_sha256=DIGEST)
        self.assertIn("bundle guard result is not PASS", reasons)

    def test_historical_import_record_is_blocked(self) -> None:
        record = enabling_authorization(record_kind=guard.HISTORICAL_IMPORT)
        reasons = phase_b.gate_reasons(ready_manifest(), record, expected_xml_sha256=DIGEST)
        self.assertTrue(any("cannot authorize submission" in reason for reason in reasons))

    def test_disabled_submission_is_blocked(self) -> None:
        record = enabling_authorization(submission={"enabled": False})
        reasons = phase_b.gate_reasons(ready_manifest(), record, expected_xml_sha256=DIGEST)
        self.assertIn("the authorization record does not enable submission", reasons)

    def test_missing_expected_digest_is_blocked(self) -> None:
        reasons = phase_b.gate_reasons(ready_manifest(), enabling_authorization(), expected_xml_sha256=None)
        self.assertIn("--expected-xml-sha256 is required for a live submission", reasons)

    def test_mismatched_expected_digest_is_blocked(self) -> None:
        reasons = phase_b.gate_reasons(
            ready_manifest(), enabling_authorization(), expected_xml_sha256="f" * 64
        )
        self.assertTrue(any("!= bundle digest" in reason for reason in reasons))

    def test_identity_mismatch_between_bundle_and_authorization_is_blocked(self) -> None:
        record = enabling_authorization(artifact_identity="draft-other-wexp-core-01")
        reasons = phase_b.gate_reasons(ready_manifest(), record, expected_xml_sha256=DIGEST)
        self.assertIn("bundle and authorization describe different artifact identities", reasons)


class TestPhaseBCommandLine(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.bundle = self.root / "bundle"
        (self.bundle / "submission").mkdir(parents=True)
        xml = self.bundle / "submission" / f"{IDENTITY}.xml"
        xml.write_text(support.MINIMAL_XML.format(identity=IDENTITY), encoding="utf-8")
        manifest = ready_manifest(
            submission_xml={"path": f"submission/{IDENTITY}.xml", "sha256": support.sha256_text(xml)}
        )
        (self.bundle / "BUNDLE-MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.digest = manifest["submission_xml"]["sha256"]
        self.authorization = self.root / "authorization.json"
        self.authorization.write_text(json.dumps(enabling_authorization(), indent=2), encoding="utf-8")

    def arguments(self, *extra: str) -> list[str]:
        return [
            "--bundle-root",
            str(self.bundle),
            "--authorization",
            str(self.authorization),
            "--expected-xml-sha256",
            self.digest,
            *extra,
        ]

    def test_default_invocation_is_a_dry_run(self) -> None:
        evidence = self.root / "dry-run.json"
        code = phase_b.main(self.arguments("--json", str(evidence)))
        self.assertEqual(code, 0)
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertEqual(payload["result"], dts.NOT_PERFORMED)
        self.assertFalse(payload["network_submission_performed"])
        self.assertFalse(payload["live_requested"])

    def test_live_without_the_environment_switch_is_blocked(self) -> None:
        # main() reaches submit_request, whose own hard guard refuses because
        # WEXP_DATATRACKER_SUBMIT is not armed in the test environment.
        evidence = self.root / "blocked.json"
        code = phase_b.main(self.arguments("--live", "--json", str(evidence)))
        self.assertEqual(code, 1)

    def test_live_with_a_blocked_bundle_never_reaches_the_client(self) -> None:
        manifest = json.loads((self.bundle / "BUNDLE-MANIFEST.json").read_text(encoding="utf-8"))
        manifest["terminal_result"] = "NOT READY — held"
        (self.bundle / "BUNDLE-MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        evidence = self.root / "blocked.json"
        code = phase_b.main(self.arguments("--live", "--json", str(evidence)))
        self.assertEqual(code, 1)
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertEqual(payload["result"], dts.NOT_PERFORMED)
        self.assertIn("bundle terminal result is 'NOT READY — held'", payload["phase_b_gate_reasons"])


if __name__ == "__main__":
    unittest.main()
