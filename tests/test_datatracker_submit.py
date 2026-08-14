"""Datatracker client tests.

These validate ``prepare_request`` exhaustively without ever invoking
``submit_request`` against a network, and prove that ``submit_request`` refuses
to transmit unless every hard guard is satisfied simultaneously.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402
import datatracker_submit as dts  # noqa: E402

IDENTITY = "draft-example-wexp-core-01"


class ClientTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.xml = support.write_xml(self.root, IDENTITY)

    def request(self, **overrides):
        parameters = {
            "user": "author@example.com",
            "artifact_identity": IDENTITY,
            "authorization_id": "PA-core-01-001",
            "guard_passed": True,
            "submission_authorized": True,
        }
        parameters.update(overrides)
        return dts.prepare_request(self.xml, **parameters)


class TestPrepareRequest(ClientTestCase):
    def test_request_matches_the_observed_server_contract(self) -> None:
        request = self.request()
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.url, "https://datatracker.ietf.org/api/submission")
        self.assertEqual(set(request.form_fields), {"user"})
        self.assertEqual(request.xml_sha256, support.sha256_text(self.xml))
        self.assertEqual(request.xml_size, self.xml.stat().st_size)

    def test_replaces_is_included_only_when_present(self) -> None:
        request = self.request(replaces=["draft-example-wexp-old"])
        self.assertEqual(request.form_fields["replaces"], "draft-example-wexp-old")

    def test_non_xml_upload_is_refused(self) -> None:
        text = self.root / "draft.txt"
        text.write_text("not xml\n", encoding="utf-8")
        with self.assertRaises(dts.SubmissionRequestError):
            dts.prepare_request(text, user="author@example.com")

    def test_missing_file_is_refused(self) -> None:
        with self.assertRaises(dts.SubmissionRequestError):
            dts.prepare_request(self.root / "absent.xml", user="author@example.com")

    def test_empty_file_is_refused(self) -> None:
        empty = self.root / "empty.xml"
        empty.write_bytes(b"")
        with self.assertRaises(dts.SubmissionRequestError):
            dts.prepare_request(empty, user="author@example.com")

    def test_non_email_user_is_refused(self) -> None:
        with self.assertRaises(dts.SubmissionRequestError):
            dts.prepare_request(self.xml, user="not-an-address")

    def test_plaintext_endpoint_is_refused(self) -> None:
        with self.assertRaises(dts.SubmissionRequestError):
            dts.prepare_request(self.xml, user="author@example.com", url="http://example.invalid/api")

    def test_malformed_replaces_entry_is_refused(self) -> None:
        with self.assertRaises(dts.SubmissionRequestError):
            self.request(replaces=["Not-A-Draft"])

    def test_multipart_body_contains_every_field_and_the_file(self) -> None:
        request = self.request(replaces=["draft-example-wexp-old"])
        body = dts.encode_multipart(request, "boundary123")
        self.assertIn(b'name="user"', body)
        self.assertIn(b'name="replaces"', body)
        self.assertIn(b'name="xml"; filename="draft-example-wexp-core-01.xml"', body)
        self.assertIn(self.xml.read_bytes(), body)
        self.assertTrue(body.endswith(b"--boundary123--\r\n"))

    def test_multiline_boundary_is_refused(self) -> None:
        with self.assertRaises(dts.SubmissionRequestError):
            dts.encode_multipart(self.request(), "bad\r\nboundary")


class TestRedaction(ClientTestCase):
    def test_preview_redacts_the_submitter_address(self) -> None:
        preview = self.request().preview()
        self.assertNotIn("author@example.com", str(preview))
        self.assertEqual(preview["fields"]["user"], "a*****@example.com")

    def test_curl_preview_redacts_the_submitter_address(self) -> None:
        self.assertNotIn("author@example.com", self.request().curl_preview())

    def test_preview_states_that_no_credential_is_required(self) -> None:
        preview = self.request().preview()
        self.assertEqual(preview["credentials_required"], [])

    def test_credential_presence_check_reveals_no_values(self) -> None:
        presence = dts.check_credentials_presence({dts.LIVE_SWITCH_NAME: dts.LIVE_SWITCH_VALUE})
        self.assertTrue(presence["live_switch_armed"])
        self.assertNotIn(dts.LIVE_SWITCH_VALUE, str(presence["note"]))
        self.assertFalse(presence["datatracker_api_key_required"])


class TestSubmitGuards(ClientTestCase):
    def test_dry_run_never_transmits_and_says_so(self) -> None:
        evidence = dts.dry_run(self.request(), environment={})
        self.assertEqual(evidence["result"], "SUBMISSION NOT PERFORMED")
        self.assertFalse(evidence["network_submission_performed"])
        self.assertIn("encoded_body_sha256", evidence)

    def test_dry_run_still_blocks_with_the_live_switch_set(self) -> None:
        evidence = dts.dry_run(
            self.request(), environment={dts.LIVE_SWITCH_NAME: dts.LIVE_SWITCH_VALUE}
        )
        self.assertEqual(evidence["result"], "SUBMISSION NOT PERFORMED")

    def test_missing_live_switch_blocks_submission(self) -> None:
        with self.assertRaises(dts.SubmissionBlocked) as caught:
            dts.submit_request(self.request(), live=True, environment={})
        self.assertIn("SUBMISSION NOT PERFORMED", str(caught.exception))
        self.assertIn(dts.LIVE_SWITCH_NAME, str(caught.exception))

    def test_wrong_live_switch_value_blocks_submission(self) -> None:
        with self.assertRaises(dts.SubmissionBlocked):
            dts.submit_request(
                self.request(), live=True, environment={dts.LIVE_SWITCH_NAME: "yes"}
            )

    def test_failed_guard_blocks_submission(self) -> None:
        with self.assertRaises(dts.SubmissionBlocked) as caught:
            dts.submit_request(
                self.request(guard_passed=False),
                live=True,
                environment={dts.LIVE_SWITCH_NAME: dts.LIVE_SWITCH_VALUE},
            )
        self.assertIn("publication guard", str(caught.exception))

    def test_unauthorized_submission_blocks_submission(self) -> None:
        with self.assertRaises(dts.SubmissionBlocked) as caught:
            dts.submit_request(
                self.request(submission_authorized=False),
                live=True,
                environment={dts.LIVE_SWITCH_NAME: dts.LIVE_SWITCH_VALUE},
            )
        self.assertIn("authorization record", str(caught.exception))

    def test_unbound_identity_blocks_submission(self) -> None:
        with self.assertRaises(dts.SubmissionBlocked):
            dts.submit_request(
                self.request(artifact_identity=""),
                live=True,
                environment={dts.LIVE_SWITCH_NAME: dts.LIVE_SWITCH_VALUE},
            )

    def test_live_false_always_blocks_even_when_everything_else_passes(self) -> None:
        reasons = dts.blocking_reasons(
            self.request(), live=False, environment={dts.LIVE_SWITCH_NAME: dts.LIVE_SWITCH_VALUE}
        )
        self.assertEqual(reasons, ["live=False (dry-run is the default)"])

    def test_all_gates_satisfied_leaves_no_blocking_reason(self) -> None:
        # This asserts the gate logic only. No transmission occurs: the request
        # is never handed to submit_request in this test.
        reasons = dts.blocking_reasons(
            self.request(), live=True, environment={dts.LIVE_SWITCH_NAME: dts.LIVE_SWITCH_VALUE}
        )
        self.assertEqual(reasons, [])


class TestSubmitCallSites(unittest.TestCase):
    def test_only_phase_b_calls_submit_request(self) -> None:
        callers = sorted(
            path.name
            for path in (support.REPO_ROOT / "scripts").glob("*.py")
            if "submit_request(" in path.read_text(encoding="utf-8")
            and path.name != "datatracker_submit.py"
        )
        self.assertEqual(callers, ["submit_publication.py"])

    def test_no_workflow_arms_the_live_switch_outside_the_submit_workflow(self) -> None:
        workflows = sorted((support.REPO_ROOT / ".github" / "workflows").glob("*.yml"))
        armed = [
            path.name
            for path in workflows
            if dts.LIVE_SWITCH_NAME in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(armed, ["ietf-publication-submit.yml"])


if __name__ == "__main__":
    unittest.main()
