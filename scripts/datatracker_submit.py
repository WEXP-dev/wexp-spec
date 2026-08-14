#!/usr/bin/env python3
"""IETF Datatracker Internet-Draft submission client with a hard prepare/submit split.

Observed server contract (``https://datatracker.ietf.org/api/submission``,
observed 2026-08-14 against Datatracker 12.71.0):

* ``POST`` with ``multipart/form-data``;
* ``user`` — required, the submitter's Datatracker account email address;
* ``xml`` — required, a single RFCXML file (XML-only; text and combined
  uploads are not supported by this interface);
* ``replaces`` — optional, comma-separated Internet-Draft names;
* no API key or bearer token participates in this endpoint;
* success returns ``{"id", "name", "rev", "status_url", ...}``;
* failure returns ``{"error", "messages"}`` with a non-2xx status;
* a successful POST only *queues* the submission. Datatracker then emails the
  authors (for ``-00``) or the previous revision's authors (for ``-01`` and
  later) and a human must click the confirmation link. Submission is therefore
  never fully unattended.

``prepare_request`` is pure: it builds and validates the exact request without
importing or touching any network machinery, and is fully unit-testable.
``submit_request`` is the only function that can reach the network, and it
refuses to run unless every hard guard is satisfied simultaneously.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


DATATRACKER_SUBMISSION_URL = "https://datatracker.ietf.org/api/submission"

#: Exact value required in the environment before a live POST is possible.
LIVE_SWITCH_NAME = "WEXP_DATATRACKER_SUBMIT"
LIVE_SWITCH_VALUE = "PUBLISH"

#: Terminal string that machine-checkable dry-run evidence must contain.
NOT_PERFORMED = "SUBMISSION NOT PERFORMED"

REDACTED = "«redacted»"


class SubmissionBlocked(RuntimeError):
    """Raised whenever a submission is attempted without full authorization."""


class SubmissionRequestError(ValueError):
    """Raised when a request cannot be constructed from the given inputs."""


@dataclass(frozen=True)
class SubmissionRequest:
    """An exact, immutable description of the request that would be sent."""

    url: str
    method: str
    xml_path: Path
    xml_filename: str
    xml_sha256: str
    xml_size: int
    user: str
    replaces: tuple[str, ...] = ()
    artifact_identity: str = ""
    authorization_id: str = ""
    #: Set only by a caller that has already run the publication guard to PASS.
    guard_passed: bool = False
    #: Set only by a caller that has confirmed the human authorization record
    #: enables submission for this exact identity.
    submission_authorized: bool = False
    extra_fields: dict[str, str] = field(default_factory=dict)

    @property
    def form_fields(self) -> dict[str, str]:
        fields = {"user": self.user}
        if self.replaces:
            fields["replaces"] = ",".join(self.replaces)
        fields.update(self.extra_fields)
        return fields

    def preview(self, *, redact_user: bool = True) -> dict[str, Any]:
        """A log-safe, machine-checkable description of the request."""

        fields = dict(self.form_fields)
        if redact_user and "user" in fields:
            fields["user"] = _redact_email(fields["user"])
        return {
            "method": self.method,
            "url": self.url,
            "content_type": "multipart/form-data",
            "fields": fields,
            "file_part": {
                "field_name": "xml",
                "filename": self.xml_filename,
                "sha256": self.xml_sha256,
                "size_bytes": self.xml_size,
                "media_type": "application/xml",
            },
            "artifact_identity": self.artifact_identity,
            "authorization_id": self.authorization_id,
            "guard_passed": self.guard_passed,
            "submission_authorized": self.submission_authorized,
            "credentials_required": [],
            "authentication_model": (
                "no API key or token; the submitter email identifies a Datatracker "
                "account and a human confirmation email completes the submission"
            ),
        }

    def curl_preview(self, *, redact_user: bool = True) -> str:
        """The equivalent curl invocation, with the submitter address redacted."""

        user = _redact_email(self.user) if redact_user else self.user
        parts = [
            "curl -sS",
            f'-F "user={user}"',
            f'-F "xml=@{self.xml_filename}"',
        ]
        if self.replaces:
            parts.append(f'-F "replaces={",".join(self.replaces)}"')
        parts.append(self.url)
        return " ".join(parts)


@dataclass(frozen=True)
class SubmissionResponse:
    status_code: int
    body: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status_code in {200, 201}


def _redact_email(value: str) -> str:
    """Keep the shape of an address without republishing it into a log."""

    if "@" not in value:
        return REDACTED
    local, _, domain = value.partition("@")
    keep = local[:1] if local else ""
    return f"{keep}{'*' * max(len(local) - 1, 1)}@{domain}"


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def prepare_request(
    xml_path: Path,
    *,
    user: str,
    replaces: Sequence[str] = (),
    artifact_identity: str = "",
    authorization_id: str = "",
    guard_passed: bool = False,
    submission_authorized: bool = False,
    url: str = DATATRACKER_SUBMISSION_URL,
) -> SubmissionRequest:
    """Build the exact submission request. Never performs network I/O."""

    if not isinstance(xml_path, Path):
        raise SubmissionRequestError("xml_path must be a Path")
    if not xml_path.is_file():
        raise SubmissionRequestError(f"submission XML does not exist: {xml_path}")
    if xml_path.suffix.lower() != ".xml":
        raise SubmissionRequestError(
            f"the submission interface accepts XML only, observed {xml_path.suffix!r}"
        )
    if not user or "@" not in user:
        raise SubmissionRequestError("user must be the submitter's account email address")
    if not url.startswith("https://"):
        raise SubmissionRequestError(f"submission URL must be https: {url!r}")

    cleaned = tuple(name.strip() for name in replaces if name and name.strip())
    for name in cleaned:
        if not name.startswith("draft-") or name != name.strip().lower():
            raise SubmissionRequestError(f"replaces entry is not an Internet-Draft name: {name!r}")

    digest, size = _sha256(xml_path)
    if size == 0:
        raise SubmissionRequestError(f"submission XML is empty: {xml_path}")

    return SubmissionRequest(
        url=url,
        method="POST",
        xml_path=xml_path,
        xml_filename=xml_path.name,
        xml_sha256=digest,
        xml_size=size,
        user=user,
        replaces=cleaned,
        artifact_identity=artifact_identity,
        authorization_id=authorization_id,
        guard_passed=guard_passed,
        submission_authorized=submission_authorized,
    )


def encode_multipart(request: SubmissionRequest, boundary: str) -> bytes:
    """Encode the request body exactly as it would be sent.

    Building the body is deliberately part of the *prepare* half so that
    dry-run coverage reaches byte-level request construction without any
    possibility of transmitting it.
    """

    if not boundary or any(character in boundary for character in "\r\n"):
        raise SubmissionRequestError("multipart boundary must be a single-line token")

    chunks: list[bytes] = []
    marker = f"--{boundary}".encode("ascii")
    for name, value in request.form_fields.items():
        chunks.append(marker + b"\r\n")
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(value.encode("utf-8") + b"\r\n")
    chunks.append(marker + b"\r\n")
    chunks.append(
        (
            f'Content-Disposition: form-data; name="xml"; filename="{request.xml_filename}"\r\n'
            "Content-Type: application/xml\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(request.xml_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks)


def blocking_reasons(request: SubmissionRequest, *, live: bool, environment: dict[str, str] | None = None) -> list[str]:
    """Every reason this request must not be transmitted. Empty means allowed."""

    env = os.environ if environment is None else environment
    reasons: list[str] = []
    if not live:
        reasons.append("live=False (dry-run is the default)")
    if env.get(LIVE_SWITCH_NAME) != LIVE_SWITCH_VALUE:
        reasons.append(f"{LIVE_SWITCH_NAME} is not set to {LIVE_SWITCH_VALUE}")
    if not request.guard_passed:
        reasons.append("publication guard did not report PASS")
    if not request.submission_authorized:
        reasons.append("the human authorization record does not enable submission")
    if not request.artifact_identity:
        reasons.append("no exact artifact identity is bound to the request")
    if not request.authorization_id:
        reasons.append("no publication authorization identity is bound to the request")
    return reasons


def submit_request(
    request: SubmissionRequest,
    *,
    live: bool = False,
    environment: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> SubmissionResponse:
    """Transmit the request. Refuses unless every hard guard is satisfied.

    This is the only function in the repository that can reach the Datatracker.
    """

    reasons = blocking_reasons(request, live=live, environment=environment)
    if reasons:
        raise SubmissionBlocked(f"{NOT_PERFORMED}: " + "; ".join(reasons))

    # Imported here so that dry-run code paths never even load network machinery.
    import urllib.error
    import urllib.request

    boundary = f"----wexp{uuid.uuid4().hex}"
    body = encode_multipart(request, boundary)
    http_request = urllib.request.Request(
        request.url,
        data=body,
        method=request.method,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "wexp-spec-publication-pipeline/1",
        },
    )
    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return SubmissionResponse(response.status, _decode(payload))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        return SubmissionResponse(exc.code, _decode(payload))


def _decode(payload: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return {"error": "non-JSON response", "raw": payload[:2000]}
    return value if isinstance(value, dict) else {"error": "unexpected JSON shape", "raw": value}


def dry_run(request: SubmissionRequest, *, environment: dict[str, str] | None = None) -> dict[str, Any]:
    """Exercise the whole path except transmission, and prove nothing was sent."""

    boundary = "----wexpdryrun0000000000000000"
    body = encode_multipart(request, boundary)
    reasons = blocking_reasons(request, live=False, environment=environment)
    transmitted = False
    error = ""
    try:
        submit_request(request, live=False, environment=environment)
    except SubmissionBlocked as exc:
        error = str(exc)
    else:  # pragma: no cover - reaching this line would be a policy failure
        transmitted = True
    if transmitted:
        raise AssertionError("dry_run transmitted a submission; this must never happen")
    return {
        "result": NOT_PERFORMED,
        "network_submission_performed": False,
        "blocking_reasons": reasons,
        "blocked_message": error,
        "request_preview": request.preview(),
        "curl_preview": request.curl_preview(),
        "encoded_body_sha256": hashlib.sha256(body).hexdigest(),
        "encoded_body_size_bytes": len(body),
        "multipart_boundary_shape": "----wexp<32 hex>",
    }


def check_credentials_presence(environment: dict[str, str] | None = None) -> dict[str, Any]:
    """Report which submission-relevant environment switches are present.

    Values are never read into the result, only presence.
    """

    env = os.environ if environment is None else environment
    return {
        "datatracker_api_key_required": False,
        "datatracker_api_key_present": False,
        "live_switch_name": LIVE_SWITCH_NAME,
        "live_switch_present": LIVE_SWITCH_NAME in env,
        "live_switch_armed": env.get(LIVE_SWITCH_NAME) == LIVE_SWITCH_VALUE,
        "note": (
            "The Datatracker submission interface takes no API key. The only "
            "secret-shaped input is the submitter's account email address, and "
            "authorization is completed by a human confirmation email."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construct and preview an I-D submission request.")
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--replaces", default="")
    parser.add_argument("--artifact-identity", default="")
    parser.add_argument("--authorization-id", default="")
    parser.add_argument("--json", dest="json_out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        request = prepare_request(
            args.xml,
            user=args.user,
            replaces=[item for item in args.replaces.split(",") if item],
            artifact_identity=args.artifact_identity,
            authorization_id=args.authorization_id,
        )
    except SubmissionRequestError as exc:
        print(f"NOT READY — {exc}", file=sys.stderr)
        return 1

    evidence = dry_run(request)
    print(json.dumps(evidence, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(NOT_PERFORMED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
