#!/usr/bin/env python3
"""Phase B — SUBMIT.

This is the only module in the repository that calls
``datatracker_submit.submit_request``. It consumes an exact Phase-A bundle by
identity and digest and refuses to submit anything else.

Without ``--live`` it performs a full dry-run and terminates with
``SUBMISSION NOT PERFORMED``. With ``--live`` it additionally requires:

* ``WEXP_DATATRACKER_SUBMIT=PUBLISH`` in the environment;
* a bundle whose terminal result is exactly ``READY FOR IETF SUBMISSION``;
* a bundle whose guard result is ``PASS``;
* an authorization record of kind ``publication_authorization`` with
  ``submission.enabled = true``;
* ``--expected-xml-sha256`` equal to the bundle's submission XML digest, so the
  operator is binding the submission to a digest they read from Phase A rather
  than to whatever happens to be on disk.

Even when every gate passes, submission is not complete: the Datatracker emails
the relevant authors and a human must click the confirmation link.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import datatracker_submit as dts  # noqa: E402
import publication_guard as guard  # noqa: E402


READY = "READY FOR IETF SUBMISSION"


def gate_reasons(
    manifest: dict[str, Any],
    authorization: dict[str, Any],
    *,
    expected_xml_sha256: str | None,
) -> list[str]:
    """Every reason this bundle must not proceed to a live submission."""

    reasons: list[str] = []
    if manifest.get("terminal_result") != READY:
        reasons.append(f"bundle terminal result is {manifest.get('terminal_result')!r}")
    if (manifest.get("guard") or {}).get("result") != "PASS":
        reasons.append("bundle guard result is not PASS")
    if authorization.get("record_kind") != guard.PUBLICATION_AUTHORIZATION:
        reasons.append(f"record_kind {authorization.get('record_kind')!r} cannot authorize submission")
    submission = authorization.get("submission")
    if not isinstance(submission, dict) or not submission.get("enabled"):
        reasons.append("the authorization record does not enable submission")
    digest = (manifest.get("submission_xml") or {}).get("sha256")
    if not digest:
        reasons.append("the bundle records no submission XML digest")
    elif expected_xml_sha256 and expected_xml_sha256 != digest:
        reasons.append(f"expected XML digest {expected_xml_sha256} != bundle digest {digest}")
    elif not expected_xml_sha256:
        reasons.append("--expected-xml-sha256 is required for a live submission")
    if manifest.get("artifact_identity") != authorization.get("artifact_identity"):
        reasons.append("bundle and authorization describe different artifact identities")
    return reasons


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--expected-xml-sha256", default=None)
    parser.add_argument(
        "--live",
        action="store_true",
        help="attempt a real Datatracker submission; every gate must also pass",
    )
    parser.add_argument("--json", dest="json_out", type=Path, default=None)
    args = parser.parse_args(argv)

    manifest = json.loads((args.bundle_root / "BUNDLE-MANIFEST.json").read_text(encoding="utf-8"))
    authorization = guard.load_authorization(args.authorization)
    identity = str(manifest.get("artifact_identity") or "")
    xml_path = args.bundle_root / (manifest.get("submission_xml") or {}).get("path", "")

    submission = authorization.get("submission") if isinstance(authorization.get("submission"), dict) else {}
    request = dts.prepare_request(
        xml_path,
        user=str(submission.get("datatracker_user") or "unset@invalid"),
        replaces=submission.get("replaces") or (),
        artifact_identity=identity,
        authorization_id=str(authorization.get("authorization_id") or ""),
        guard_passed=(manifest.get("guard") or {}).get("result") == "PASS",
        submission_authorized=bool(submission.get("enabled")),
    )

    reasons = gate_reasons(manifest, authorization, expected_xml_sha256=args.expected_xml_sha256)
    if not args.live or reasons:
        evidence = dts.dry_run(request)
        evidence["phase_b_gate_reasons"] = reasons
        evidence["live_requested"] = args.live
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        for reason in reasons:
            print(f"BLOCKED: {reason}", file=sys.stderr)
        print(dts.NOT_PERFORMED)
        return 1 if (args.live and reasons) else 0

    try:
        response = dts.submit_request(request, live=True)
    except dts.SubmissionBlocked as exc:
        # The client refused at its own hard guard, e.g. the live switch is not
        # armed in this environment. Report it as a blocked run, not a crash.
        print(f"BLOCKED: {exc}", file=sys.stderr)
        print(dts.NOT_PERFORMED)
        return 1
    outcome = {
        "artifact_identity": identity,
        "authorization_id": authorization.get("authorization_id"),
        "submitted_xml_sha256": request.xml_sha256,
        "http_status": response.status_code,
        "response": response.body,
        "confirmation_required": True,
        "confirmation_note": (
            "Datatracker has emailed the relevant authors. The submission is not "
            "complete until a human opens that message and confirms."
        ),
    }
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(outcome, indent=2))
    if not response.ok:
        print(f"SUBMISSION FAILED — HTTP {response.status_code}", file=sys.stderr)
        return 1
    print("SUBMISSION QUEUED — AWAITING HUMAN EMAIL CONFIRMATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
