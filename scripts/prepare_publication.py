#!/usr/bin/env python3
"""Phase A — PREPARE.

Build a complete, self-describing publication bundle for one exact
Internet-Draft revision and decide whether it is fit to submit. This phase is
safe to run repeatedly: it never submits, and it proves that it did not.

Terminal result on stdout is exactly one of::

    READY FOR IETF SUBMISSION
    NOT READY — <reason>

and, unconditionally::

    SUBMISSION NOT PERFORMED

Phase B (submit) consumes this bundle by identity and must not rebuild a
different draft. The bundle therefore pins the exact XML digest, the guard
verdict, the toolchain versions, and the request that Phase B would send.
"""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import datatracker_submit as dts  # noqa: E402
import publication_guard as guard  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATIONS = ROOT / "publication" / "authorizations"

READY = "READY FOR IETF SUBMISSION"
NOT_READY = "NOT READY"


@dataclass(frozen=True)
class BuildOutcome:
    report: guard.BuildReport
    text_path: Path | None
    html_path: Path | None
    lint_path: Path | None


def _tool_version(executable: str, *arguments: str) -> str:
    if shutil.which(executable) is None:
        return ""
    result = subprocess.run(
        [executable, *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    first = result.stdout.strip().splitlines()
    return first[0].strip() if first else ""


def _run(command: Sequence[str], *, timeout: float = 900.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def classify_idnits(payload: dict[str, Any]) -> tuple[str, list[str]]:
    """Map an idnits v3 JSON report onto a guard lint status.

    idnits reports ``result: fail`` for warning-only documents and exits 0 in
    both cases, so neither field alone is a usable gate. Errors block; warnings
    are recorded and surfaced but do not block, because the authoritative
    submission checks are the ones Datatracker runs server-side.
    """

    counts = payload.get("nitsBySeverity") or {}
    errors = int(counts.get("error", 0) or 0)
    warnings = int(counts.get("warning", 0) or 0)
    messages = [
        f"idnits {nit.get('severity', '?')} {nit.get('code', '?')}: {nit.get('desc', '')}"
        for nit in (payload.get("nits") or [])
        if nit.get("severity") == "ValidationError"
    ]
    if errors:
        return "FAIL", messages
    if warnings:
        return "PASS_WITH_WARNINGS", [f"idnits reported {warnings} warning(s), 0 error(s)"]
    return "PASS", []


def build_draft(xml_path: Path, output_dir: Path, identity: str) -> BuildOutcome:
    """Parse, render and lint the exact authorized XML."""

    output_dir.mkdir(parents=True, exist_ok=True)
    messages: list[str] = []
    versions: dict[str, str] = {}

    xml_parsed = True
    try:
        guard.read_xml_metadata(xml_path)
    except Exception as exc:  # noqa: BLE001 - any parse failure is a build failure
        xml_parsed = False
        messages.append(f"RFCXML parse failed: {exc}")

    text_path = output_dir / f"{identity}.txt"
    html_path = output_dir / f"{identity}.html"
    text_rendered = False
    html_rendered = False

    xml2rfc_version = _tool_version("xml2rfc", "--version")
    if xml2rfc_version:
        versions["xml2rfc"] = xml2rfc_version
        if xml_parsed:
            for flag, target in (("--text", text_path), ("--html", html_path)):
                result = _run(["xml2rfc", flag, "--out", str(target), str(xml_path)])
                if result.returncode == 0 and target.is_file() and target.stat().st_size > 0:
                    if flag == "--text":
                        text_rendered = True
                    else:
                        html_rendered = True
                else:
                    messages.append(
                        f"xml2rfc {flag} failed (exit {result.returncode}): "
                        f"{result.stdout.strip().splitlines()[-1] if result.stdout.strip() else 'no output'}"
                    )
    else:
        messages.append("xml2rfc is not installed; rendering could not be attempted")

    lint_path: Path | None = None
    lint_ran = False
    lint_status = "NOT_RUN"
    idnits_version = _tool_version("idnits", "--version")
    if idnits_version:
        versions["idnits"] = idnits_version
        lint_path = output_dir / "idnits.json"
        result = _run(
            [
                "idnits",
                "--mode",
                "submission",
                "--output",
                "json",
                "--offline",
                "--no-progress",
                str(xml_path),
            ]
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            messages.append("idnits produced no parsable JSON report")
            payload = None
        if isinstance(payload, dict):
            # idnits records the absolute input path. Replace it with the bare
            # filename so the bundle is reproducible across machines and cannot
            # leak a checkout location into a published artifact.
            if isinstance(payload.get("file"), dict):
                payload["file"]["path"] = xml_path.name
            lint_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            lint_ran = True
            lint_status, lint_messages = classify_idnits(payload)
            messages.extend(lint_messages)
    else:
        messages.append("idnits is not installed; the draft linter could not be run")

    report = guard.BuildReport(
        xml_parsed=xml_parsed,
        text_rendered=text_rendered,
        html_rendered=html_rendered,
        lint_ran=lint_ran,
        lint_status=lint_status,
        tool_versions=versions,
        messages=tuple(messages),
    )
    return BuildOutcome(
        report=report,
        text_path=text_path if text_rendered else None,
        html_path=html_path if html_rendered else None,
        lint_path=lint_path if lint_ran else None,
    )


def previous_revision_text(repo_root: Path, authorization: dict[str, Any]) -> Path | None:
    """Locate the previously published rendered text, if this repository has it."""

    revision = str(authorization.get("revision", ""))
    draft_name = str(authorization.get("draft_name", ""))
    if not revision.isdigit() or int(revision) == 0 or not draft_name:
        return None
    previous = f"{int(revision) - 1:02d}"
    declared = authorization.get("previous_revision")
    if isinstance(declared, dict) and isinstance(declared.get("text_path"), str):
        candidate = repo_root / declared["text_path"]
        return candidate if candidate.is_file() else None
    for candidate in repo_root.glob(f"drafts/**/{previous}/{draft_name}-{previous}.txt"):
        return candidate
    return None


def render_diff(previous: Path | None, current: Path | None, target: Path, identity: str) -> str:
    """Write a unified diff against the previous published revision."""

    target.parent.mkdir(parents=True, exist_ok=True)
    if previous is None:
        target.write_text(
            "no previous published revision is available in this repository\n", encoding="utf-8"
        )
        return "unavailable: no previous revision in repository"
    if current is None:
        target.write_text("current revision was not rendered; diff not computed\n", encoding="utf-8")
        return "unavailable: current revision was not rendered"
    lines = difflib.unified_diff(
        previous.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True),
        current.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True),
        fromfile=previous.name,
        tofile=f"{identity}.txt",
    )
    target.write_text("".join(lines), encoding="utf-8")
    return f"unified diff of rendered text against {previous.name}"


def write_sha256sums(bundle_root: Path) -> Path:
    target = bundle_root / "SHA256SUMS"
    entries: list[str] = []
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file() or path.name in {"SHA256SUMS", "RESULT.txt"}:
            continue
        relative = path.relative_to(bundle_root).as_posix()
        entries.append(f"{guard.sha256_file(path)}  {relative}")
    target.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return target


def resolve_authorization(repo_root: Path, identity: str | None, path: Path | None) -> Path:
    if path is not None:
        return path.resolve()
    if not identity:
        raise guard.GuardError("either --identity or --authorization is required")
    candidate = repo_root / "publication" / "authorizations" / f"{identity}.json"
    if not candidate.is_file():
        raise guard.GuardError(f"no publication authorization record for {identity}")
    return candidate.resolve()


def prepare(
    repo_root: Path,
    authorization_path: Path,
    *,
    triggering_ref: str | None,
    bundle_root: Path,
    require_tag_signature: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Run Phase A end to end and return (terminal_result, bundle_manifest)."""

    authorization = guard.load_authorization(authorization_path)
    identity = str(authorization.get("artifact_identity") or "unknown-artifact")
    submission = authorization.get("submission") if isinstance(authorization.get("submission"), dict) else {}

    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    submission_dir = bundle_root / "submission"
    rendered_dir = bundle_root / "rendered"
    evidence_dir = bundle_root / "evidence"
    for directory in (submission_dir, rendered_dir, evidence_dir):
        directory.mkdir(parents=True, exist_ok=True)

    authorized = authorization.get("authorized_xml") or {}
    relative = authorized.get("path") if isinstance(authorized, dict) else None
    blockers: list[str] = []
    submission_xml: Path | None = None
    if isinstance(relative, str) and (repo_root / relative).is_file():
        submission_xml = submission_dir / f"{identity}.xml"
        shutil.copyfile(repo_root / relative, submission_xml)
    else:
        blockers.append(f"authorized XML is missing: {relative!r}")

    build = BuildOutcome(
        report=guard.BuildReport(False, False, False, False, "NOT_RUN"),
        text_path=None,
        html_path=None,
        lint_path=None,
    )
    if submission_xml is not None:
        build = build_draft(submission_xml, rendered_dir, identity)
        if build.lint_path is not None:
            shutil.move(str(build.lint_path), evidence_dir / "idnits.json")

    diff_note = render_diff(
        previous_revision_text(repo_root, authorization),
        build.text_path,
        bundle_root / "diff" / f"{identity}.diff",
        identity,
    )

    scan_paths = [path for path in bundle_root.rglob("*") if path.is_file()]
    context = guard.build_context(
        repo_root,
        authorization_path,
        triggering_ref=triggering_ref,
        submission_xml_sha256=guard.sha256_file(submission_xml) if submission_xml else None,
        build=build.report,
        scan_paths=scan_paths,
        require_tag_signature=require_tag_signature,
    )
    report = guard.run_checks(context)
    (evidence_dir / "guard-report.json").write_text(
        json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8"
    )
    (evidence_dir / "build-report.json").write_text(
        json.dumps(build.report.as_dict(), indent=2) + "\n", encoding="utf-8"
    )

    request_preview: dict[str, Any] | None = None
    dry_run_evidence: dict[str, Any] = {
        "result": dts.NOT_PERFORMED,
        "network_submission_performed": False,
        "blocking_reasons": ["submission request could not be constructed"],
    }
    if submission_xml is not None:
        try:
            request = dts.prepare_request(
                submission_xml,
                user=str(submission.get("datatracker_user") or "unset@invalid"),
                replaces=submission.get("replaces") or (),
                artifact_identity=identity,
                authorization_id=str(authorization.get("authorization_id") or ""),
                guard_passed=report.ok,
                submission_authorized=bool(submission.get("enabled")),
            )
        except dts.SubmissionRequestError as exc:
            blockers.append(f"submission request could not be constructed: {exc}")
        else:
            request_preview = request.preview()
            dry_run_evidence = dts.dry_run(request)

    (evidence_dir / "submission-request-preview.json").write_text(
        json.dumps(request_preview or {}, indent=2) + "\n", encoding="utf-8"
    )
    (evidence_dir / "dry-run.json").write_text(
        json.dumps(dry_run_evidence, indent=2) + "\n", encoding="utf-8"
    )
    (evidence_dir / "credentials-presence.json").write_text(
        json.dumps(dts.check_credentials_presence(), indent=2) + "\n", encoding="utf-8"
    )

    if not report.ok:
        blockers.append(f"publication guard failed: {report.first_failure}")
    if not submission.get("enabled"):
        reason = str(submission.get("reason") or "the authorization record does not enable submission")
        blockers.append(f"submission is not authorized for {identity}: {reason}")

    terminal = READY if not blockers else f"{NOT_READY} — {'; '.join(blockers)}"

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "bundle_kind": "wexp-ietf-publication-bundle",
        "phase": "A-PREPARE",
        "artifact_identity": identity,
        "authorization": {
            "path": authorization_path.relative_to(repo_root).as_posix()
            if authorization_path.is_relative_to(repo_root)
            else str(authorization_path),
            "authorization_id": authorization.get("authorization_id"),
            "sha256": guard.sha256_file(authorization_path),
            "authorized_by": authorization.get("authorized_by"),
        },
        "publication_candidate": authorization.get("publication_candidate"),
        "source": {
            "triggering_ref": triggering_ref,
            "head_commit": context.head_commit,
            "tag_commit": context.tag_commit,
            "authorized_base_commits": list(context.authorized_base_commits),
            "workspace_clean": context.workspace_clean,
        },
        "submission_xml": {
            "path": f"submission/{identity}.xml",
            "sha256": guard.sha256_file(submission_xml) if submission_xml else None,
            "size_bytes": submission_xml.stat().st_size if submission_xml else None,
        },
        "rendered": {
            "text": f"rendered/{identity}.txt" if build.text_path else None,
            "html": f"rendered/{identity}.html" if build.html_path else None,
        },
        "diff": {"path": f"diff/{identity}.diff", "note": diff_note},
        "build": build.report.as_dict(),
        "guard": {"result": report.as_dict()["result"], "path": "evidence/guard-report.json"},
        "submission_metadata_preview": request_preview,
        "dry_run": {
            "path": "evidence/dry-run.json",
            "result": dry_run_evidence.get("result"),
            "network_submission_performed": dry_run_evidence.get("network_submission_performed"),
        },
        "terminal_result": terminal,
        "submission_performed": False,
        "non_claims": [
            "A prepared bundle is not an IETF submission, publication, or acceptance.",
            "A passing guard does not establish WEXP semantic correctness or conformance.",
            "Rendered text and HTML are regenerated representations, not the submitted bytes.",
        ],
    }
    (bundle_root / "BUNDLE-MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    write_sha256sums(bundle_root)
    (bundle_root / "RESULT.txt").write_text(
        f"{terminal}\n{dts.NOT_PERFORMED}\n", encoding="utf-8"
    )
    return terminal, manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", default=None, help="e.g. draft-sergeev-wexp-core-01")
    parser.add_argument("--authorization", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--ref", dest="triggering_ref", default=None)
    parser.add_argument("--bundle-root", type=Path, default=None)
    parser.add_argument(
        "--no-require-signature",
        action="store_true",
        help="local rehearsal only; publication workflows never set this",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    try:
        authorization_path = resolve_authorization(repo_root, args.identity, args.authorization)
    except guard.GuardError as exc:
        print(f"{NOT_READY} — {exc}")
        print(dts.NOT_PERFORMED)
        return 1

    identity = args.identity or authorization_path.stem
    bundle_root = args.bundle_root or (repo_root / "build" / "publication" / identity)
    terminal, _ = prepare(
        repo_root,
        authorization_path,
        triggering_ref=args.triggering_ref,
        bundle_root=bundle_root.resolve(),
        require_tag_signature=not args.no_require_signature,
    )
    print(f"bundle: {bundle_root}")
    print(terminal)
    print(dts.NOT_PERFORMED)
    return 0 if terminal == READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
