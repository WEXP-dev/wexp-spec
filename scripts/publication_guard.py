#!/usr/bin/env python3
"""WEXP publication guard: fail-closed checks that must pass before any
Internet-Draft submission is even constructed.

The guard never performs network I/O and never submits anything. It answers a
single question about an exact proposed publication event::

    is this exact tag, commit, authorization record and XML byte string the one
    a human authorized, and is it internally consistent?

Any check that is not conclusively PASS is a FAIL. Missing evidence is a
failure, not a pass. Checks are identified as ``G01``..``G14`` and correspond
one-to-one to the publication safety requirements documented in
``publication/README.md``.

The module separates three concerns so the policy layer stays unit-testable
without a repository, a build, or a network:

``collect_git_facts``   observes the repository (subprocess, read-only);
``GuardContext``        a plain value object describing the proposed event;
``run_checks``          pure policy over that value object.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]

PASS = "PASS"
FAIL = "FAIL"

#: An allowed publication tag is exactly an Internet-Draft revision identity.
PUBLICATION_TAG_RE = re.compile(r"^draft-[a-z0-9]+(?:-[a-z0-9]+)*-(?P<rev>[0-9]{2})$")
DRAFT_NAME_RE = re.compile(r"^draft-[a-z0-9]+(?:-[a-z0-9]+)*$")
REVISION_RE = re.compile(r"^[0-9]{2}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FLOATING_REF_RE = re.compile(
    r"(?:^|[/@:\s])(?:HEAD|main|master|latest)(?:$|[/?#\s])", re.IGNORECASE
)

#: A record that can authorize a submission, versus one that documents an
#: artifact this pipeline must never submit.
PUBLICATION_AUTHORIZATION = "publication_authorization"
HISTORICAL_IMPORT = "historical_import_non_authorization"
RECORD_KINDS = frozenset({PUBLICATION_AUTHORIZATION, HISTORICAL_IMPORT})

#: The only public WEXP repositories. This is an allowlist on purpose: a
#: denylist would have to name the private repositories in a public file, which
#: is exactly the disclosure this check exists to prevent, and would silently
#: miss any repository created later.
PUBLIC_WEXP_REPOSITORIES = frozenset({"wexp-spec", "wexp-vectors", "wexp-ref"})
WEXP_REPOSITORY_RE = re.compile(r"WEXP-dev/(?P<slug>[A-Za-z0-9._-]+)")

#: Absolute paths from a developer machine or a CI runner checkout.
LOCAL_PATH_RE = re.compile(
    r"/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\|/private/(?:tmp|var)/"
)

#: A Publication Candidate identifier belongs in an authorization record. It
#: must never appear inside an artifact that would be published.
CANDIDATE_ID_RE = re.compile(r"\bPC-(?:[a-z0-9]+-)+[0-9]{2}-[0-9]{3}\b")

#: Credential shapes that must never reach a bundle, artifact, or log.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("datatracker-apikey", re.compile(r"\bapikey\s*=\s*[A-Za-z0-9_\-]{16,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer-header", re.compile(r"\bAuthorization:\s*(?:Bearer|Basic)\s+\S{8,}")),
)

#: Extensions worth scanning for secrets/private markers. Rendered HTML and TXT
#: are derived from the XML, but they are scanned anyway because they are what
#: a reader receives.
SCANNABLE_SUFFIXES = frozenset({".xml", ".txt", ".html", ".json", ".md", ".diff", ""})


class GuardError(ValueError):
    """Raised when guard inputs are structurally unusable."""


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    title: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GuardReport:
    identity: str
    checks: tuple[CheckResult, ...]

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if check.status != PASS)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def first_failure(self) -> str:
        failures = self.failures
        return "" if not failures else f"{failures[0].check_id}: {failures[0].detail}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_identity": self.identity,
            "result": "PASS" if self.ok else "FAIL",
            "checks": [check.as_dict() for check in self.checks],
            "failures": [check.as_dict() for check in self.failures],
        }


@dataclass(frozen=True)
class BuildReport:
    """Outcome of the render/lint stage, produced by ``prepare_publication``."""

    xml_parsed: bool
    text_rendered: bool
    html_rendered: bool
    lint_ran: bool
    lint_status: str
    tool_versions: dict[str, str] = field(default_factory=dict)
    messages: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "xml_parsed": self.xml_parsed,
            "text_rendered": self.text_rendered,
            "html_rendered": self.html_rendered,
            "lint_ran": self.lint_ran,
            "lint_status": self.lint_status,
            "tool_versions": dict(self.tool_versions),
            "messages": list(self.messages),
        }


@dataclass(frozen=True)
class GuardContext:
    """Every fact the guard is allowed to reason about."""

    repo_root: Path
    authorization: dict[str, Any]
    authorization_path: Path
    #: Ref that triggered the publication attempt, e.g. ``refs/tags/draft-x-01``.
    triggering_ref: str | None = None
    #: Commit the triggering tag resolves to.
    tag_commit: str | None = None
    #: Commit currently checked out.
    head_commit: str | None = None
    #: Commits that represent authorized public spec state (normally origin/main).
    authorized_base_commits: tuple[str, ...] = ()
    #: True when ``tag_commit`` is ``head_commit`` or one of its ancestors' tips.
    commit_on_authorized_state: bool | None = None
    #: None means "not observed"; the guard treats that as a failure when required.
    tag_is_annotated: bool | None = None
    tag_signature_verified: bool | None = None
    require_tag_signature: bool = True
    workspace_clean: bool | None = None
    build: BuildReport | None = None
    #: SHA-256 of the exact bytes that would be uploaded.
    submission_xml_sha256: str | None = None
    #: Extra files (bundle contents) to scan for secrets and private markers.
    scan_paths: tuple[Path, ...] = ()


# --------------------------------------------------------------------------
# observation helpers
# --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo_root: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def collect_git_facts(repo_root: Path, tag: str | None) -> dict[str, Any]:
    """Observe the repository read-only. Unobservable facts stay ``None``."""

    facts: dict[str, Any] = {
        "head_commit": None,
        "tag_commit": None,
        "tag_is_annotated": None,
        "tag_signature_verified": None,
        "workspace_clean": None,
        "authorized_base_commits": (),
        "commit_on_authorized_state": None,
    }

    head = _git(repo_root, ["rev-parse", "HEAD"])
    if head.returncode == 0:
        facts["head_commit"] = head.stdout.strip()

    status = _git(repo_root, ["status", "--porcelain"])
    if status.returncode == 0:
        facts["workspace_clean"] = status.stdout.strip() == ""

    bases: list[str] = []
    for ref in ("refs/remotes/origin/main", "refs/heads/main"):
        resolved = _git(repo_root, ["rev-parse", "--verify", "--quiet", ref + "^{commit}"])
        if resolved.returncode == 0 and resolved.stdout.strip():
            bases.append(resolved.stdout.strip())
    facts["authorized_base_commits"] = tuple(dict.fromkeys(bases))

    if tag:
        resolved = _git(repo_root, ["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}"])
        if resolved.returncode == 0 and resolved.stdout.strip():
            facts["tag_commit"] = resolved.stdout.strip()
        kind = _git(repo_root, ["cat-file", "-t", f"refs/tags/{tag}"])
        if kind.returncode == 0:
            facts["tag_is_annotated"] = kind.stdout.strip() == "tag"
        verified = _git(repo_root, ["tag", "-v", tag])
        if facts["tag_is_annotated"]:
            facts["tag_signature_verified"] = verified.returncode == 0

    if facts["tag_commit"] and facts["authorized_base_commits"]:
        facts["commit_on_authorized_state"] = any(
            _git(repo_root, ["merge-base", "--is-ancestor", facts["tag_commit"], base]).returncode == 0
            or facts["tag_commit"] == base
            for base in facts["authorized_base_commits"]
        )
    return facts


def load_authorization(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardError(f"{path}: unreadable authorization record: {exc}") from exc
    if not isinstance(value, dict):
        raise GuardError(f"{path}: authorization record must be a JSON object")
    return value


def scan_bytes(data: bytes, label: str, *, forbid_candidate_ids: bool = True) -> list[str]:
    """Return findings for secret shapes and private references in one blob."""

    findings: list[str] = []
    text = data.decode("utf-8", errors="replace")
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(f"{label}: possible {name}")
    for match in WEXP_REPOSITORY_RE.finditer(text):
        slug = match.group("slug")
        if slug not in PUBLIC_WEXP_REPOSITORIES:
            findings.append(f"{label}: private marker reference to a non-public repository {slug!r}")
    for match in LOCAL_PATH_RE.finditer(text):
        findings.append(f"{label}: private marker local filesystem path {match.group(0)!r}")
    if forbid_candidate_ids:
        for match in CANDIDATE_ID_RE.finditer(text):
            findings.append(f"{label}: private marker Publication Candidate identifier {match.group(0)!r}")
    return findings


def scan_paths_for_leaks(paths: Iterable[Path], *, forbid_candidate_ids: bool = True) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in SCANNABLE_SUFFIXES:
            continue
        findings.extend(
            scan_bytes(path.read_bytes(), path.name, forbid_candidate_ids=forbid_candidate_ids)
        )
    return findings


def read_xml_metadata(path: Path) -> dict[str, Any]:
    """Extract the RFCXML series metadata the guard binds a submission to."""

    root = ET.parse(path).getroot()
    if root.tag != "rfc":
        raise GuardError(f"{path}: root element must be <rfc>, observed <{root.tag}>")
    # Only the document's own front matter counts. <reference> blocks carry
    # seriesInfo for every cited Internet-Draft, and those must not be mistaken
    # for this document's series identity.
    front = root.find("front")
    series = [
        dict(element.attrib)
        for element in (front.findall("seriesInfo") if front is not None else [])
        if element.attrib.get("name") == "Internet-Draft"
    ]
    return {
        "docName": root.attrib.get("docName"),
        "category": root.attrib.get("category"),
        "ipr": root.attrib.get("ipr"),
        "submissionType": root.attrib.get("submissionType"),
        "internet_draft_series": series,
    }


# --------------------------------------------------------------------------
# policy
# --------------------------------------------------------------------------


def _ok(check_id: str, title: str, detail: str) -> CheckResult:
    return CheckResult(check_id, title, PASS, detail)


def _no(check_id: str, title: str, detail: str) -> CheckResult:
    return CheckResult(check_id, title, FAIL, detail)


def _expected_tag(authorization: dict[str, Any]) -> str:
    value = authorization.get("publication_tag")
    return value if isinstance(value, str) else ""


def _artifact_identity(authorization: dict[str, Any]) -> str:
    value = authorization.get("artifact_identity")
    return value if isinstance(value, str) else ""


def _check_authorization_shape(context: GuardContext) -> list[CheckResult]:
    """G08: the authorization record itself is present, exact and self-consistent."""

    authorization = context.authorization
    problems: list[str] = []
    kind = authorization.get("record_kind", PUBLICATION_AUTHORIZATION)
    if kind not in RECORD_KINDS:
        problems.append(f"unknown record_kind: {kind!r}")
    required = [
        "schema_version",
        "record_kind",
        "authorization_id",
        "draft_name",
        "revision",
        "artifact_identity",
        "publication_tag",
        "publication_candidate",
        "authorized_xml",
        "submission",
    ]
    if kind == PUBLICATION_AUTHORIZATION:
        required.append("authorized_by")
    missing = [key for key in required if key not in authorization]
    if missing:
        problems.append("missing fields: " + ", ".join(sorted(missing)))

    draft_name = authorization.get("draft_name")
    revision = authorization.get("revision")
    identity = authorization.get("artifact_identity")
    tag = authorization.get("publication_tag")
    if isinstance(draft_name, str) and not DRAFT_NAME_RE.fullmatch(draft_name):
        problems.append(f"draft_name is not an Internet-Draft name: {draft_name!r}")
    if isinstance(revision, str) and not REVISION_RE.fullmatch(revision):
        problems.append(f"revision must be two digits: {revision!r}")
    if isinstance(draft_name, str) and isinstance(revision, str):
        expected_identity = f"{draft_name}-{revision}"
        if identity != expected_identity:
            problems.append(
                f"artifact_identity {identity!r} != draft_name-revision {expected_identity!r}"
            )
        if tag != expected_identity:
            problems.append(
                f"publication_tag {tag!r} != artifact_identity {expected_identity!r}"
            )

    if kind == PUBLICATION_AUTHORIZATION:
        authorized_by = authorization.get("authorized_by")
        if not isinstance(authorized_by, dict) or not str(authorized_by.get("identity", "")).strip():
            problems.append("authorized_by.identity is required")
        elif not str(authorized_by.get("date", "")).strip():
            problems.append("authorized_by.date is required")

    submission = authorization.get("submission")
    if not isinstance(submission, dict):
        problems.append("submission must be an object")
    elif not isinstance(submission.get("enabled"), bool):
        problems.append("submission.enabled must be a boolean")
    elif submission["enabled"] and kind != PUBLICATION_AUTHORIZATION:
        problems.append(f"a {kind!r} record must never enable submission")
    elif submission["enabled"] and not str(submission.get("datatracker_user", "")).strip():
        problems.append("submission.datatracker_user is required when submission is enabled")

    title = "publication authorization record is present and exact"
    if problems:
        return [_no("G08", title, "; ".join(problems))]
    return [
        _ok(
            "G08",
            title,
            f"{authorization['authorization_id']} authorizes {identity} "
            f"(submission enabled={authorization['submission']['enabled']})",
        )
    ]


def _check_candidate_identity(context: GuardContext) -> list[CheckResult]:
    """G09: the Publication Candidate identity is present, exact and unpinned-free."""

    title = "Publication Candidate identity is present and exact"
    kind = context.authorization.get("record_kind", PUBLICATION_AUTHORIZATION)
    candidate = context.authorization.get("publication_candidate")
    if kind != PUBLICATION_AUTHORIZATION:
        note = ""
        if isinstance(candidate, dict):
            note = str(candidate.get("status") or "")
        return [_no("G09", title, note or f"a {kind!r} record carries no Publication Candidate")]
    if not isinstance(candidate, dict):
        return [_no("G09", title, "publication_candidate must be an object")]

    problems: list[str] = []
    candidate_id = candidate.get("candidate_id")
    if not isinstance(candidate_id, str) or not re.fullmatch(
        r"PC-(?:[a-z0-9]+-)+[0-9]{2}-[0-9]{3}", candidate_id
    ):
        problems.append(f"candidate_id is not a WEXP Candidate ID: {candidate_id!r}")
    for key in ("source_commit",):
        value = candidate.get(key)
        if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
            problems.append(f"{key} must be exactly 40 lowercase hexadecimal characters")
    for key in ("candidate_tree_sha256", "authorized_xml_sha256"):
        value = candidate.get(key)
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            problems.append(f"{key} must be exactly 64 lowercase hexadecimal characters")
    workspace = candidate.get("source_workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        problems.append("source_workspace label is required")
    for key, value in candidate.items():
        if isinstance(value, str) and FLOATING_REF_RE.search(value):
            problems.append(f"floating identity is forbidden in {key}: {value!r}")

    if problems:
        return [_no("G09", title, "; ".join(problems))]
    return [
        _ok(
            "G09",
            title,
            f"{candidate['candidate_id']} tree={candidate['candidate_tree_sha256']} "
            f"source_commit={candidate['source_commit']}",
        )
    ]


def _check_trigger(context: GuardContext) -> list[CheckResult]:
    """G01: the triggering ref is an allowed, exact publication tag."""

    title = "triggering ref is an allowed publication tag"
    ref = context.triggering_ref
    if not ref:
        return [_no("G01", title, "no triggering ref was supplied")]
    if not ref.startswith("refs/tags/"):
        return [_no("G01", title, f"publication requires a tag ref, observed {ref!r}")]
    tag = ref[len("refs/tags/") :]
    match = PUBLICATION_TAG_RE.fullmatch(tag)
    if not match:
        return [_no("G01", title, f"{tag!r} is not an exact draft-<name>-<NN> tag")]
    expected = _expected_tag(context.authorization)
    if tag != expected:
        return [_no("G01", title, f"tag {tag!r} != authorized tag {expected!r}")]
    return [_ok("G01", title, f"refs/tags/{tag}")]


def _check_tag_commit(context: GuardContext) -> list[CheckResult]:
    results: list[CheckResult] = []

    title = "tag resolves to the exact expected commit"
    if not context.tag_commit or not COMMIT_RE.fullmatch(context.tag_commit):
        results.append(_no("G02", title, "tag does not resolve to a 40-hex commit"))
    elif context.head_commit and context.head_commit != context.tag_commit:
        results.append(
            _no(
                "G02",
                title,
                f"checked-out commit {context.head_commit} != tag commit {context.tag_commit}",
            )
        )
    else:
        results.append(_ok("G02", title, context.tag_commit))

    title = "commit is on or derived from authorized public spec state"
    if not context.authorized_base_commits:
        results.append(_no("G03", title, "no authorized base commit was observed"))
    elif context.commit_on_authorized_state is not True:
        results.append(
            _no(
                "G03",
                title,
                "tag commit is not contained in "
                + ", ".join(context.authorized_base_commits),
            )
        )
    else:
        results.append(
            _ok("G03", title, "contained in " + ", ".join(context.authorized_base_commits))
        )

    title = "tag signature policy passes"
    if not context.require_tag_signature:
        results.append(_ok("G04", title, "signature not required by policy for this event"))
    elif context.tag_is_annotated is not True:
        results.append(_no("G04", title, "publication tag must be an annotated tag object"))
    elif context.tag_signature_verified is not True:
        results.append(_no("G04", title, "publication tag signature did not verify"))
    else:
        results.append(_ok("G04", title, "annotated tag signature verified"))
    return results


def _check_xml_identity(context: GuardContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    authorization = context.authorization
    authorized = authorization.get("authorized_xml")
    identity = _artifact_identity(authorization)

    title = "exact draft name and revision match the tag"
    tag = _expected_tag(authorization)
    match = PUBLICATION_TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
    if not match:
        results.append(_no("G05", title, f"authorized tag {tag!r} is malformed"))
    elif match.group("rev") != authorization.get("revision"):
        results.append(
            _no("G05", title, f"tag revision {match.group('rev')!r} != {authorization.get('revision')!r}")
        )
    else:
        results.append(_ok("G05", title, f"{identity}"))

    title = "XML source identity is known"
    xml_path: Path | None = None
    if not isinstance(authorized, dict):
        results.append(_no("G06", title, "authorized_xml must be an object"))
    else:
        relative = authorized.get("path")
        expected = authorized.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            results.append(_no("G06", title, "authorized_xml.path and .sha256 must be strings"))
        elif not SHA256_RE.fullmatch(expected):
            results.append(_no("G06", title, "authorized_xml.sha256 must be 64 lowercase hex"))
        else:
            candidate = (context.repo_root / relative).resolve()
            try:
                candidate.relative_to(context.repo_root.resolve())
            except ValueError:
                results.append(_no("G06", title, f"authorized_xml.path escapes repository: {relative!r}"))
            else:
                if not candidate.is_file():
                    results.append(_no("G06", title, f"authorized XML not found: {relative}"))
                else:
                    actual = sha256_file(candidate)
                    if actual != expected:
                        results.append(
                            _no("G06", title, f"{relative}: observed {actual}, authorized {expected}")
                        )
                    else:
                        xml_path = candidate
                        results.append(_ok("G06", title, f"{relative} sha256={actual}"))

    title = "XML docName and series metadata match the intended revision"
    if xml_path is None:
        results.append(_no("G07", title, "authorized XML was not identified"))
    else:
        try:
            metadata = read_xml_metadata(xml_path)
        except (ET.ParseError, GuardError, OSError) as exc:
            results.append(_no("G07", title, f"unreadable RFCXML metadata: {exc}"))
        else:
            problems: list[str] = []
            if metadata["docName"] != identity:
                problems.append(f"docName {metadata['docName']!r} != {identity!r}")
            expected_type = authorization.get("expected_submission_type", "IETF")
            if metadata["submissionType"] != expected_type:
                problems.append(
                    f"submissionType {metadata['submissionType']!r} != {expected_type!r}"
                )
            if not metadata["ipr"]:
                problems.append("ipr attribute is required on <rfc>")
            for series in metadata["internet_draft_series"]:
                value = series.get("value")
                if value and value != identity:
                    problems.append(f"Internet-Draft seriesInfo value {value!r} != {identity!r}")
            if problems:
                results.append(_no("G07", title, "; ".join(problems)))
            else:
                results.append(
                    _ok(
                        "G07",
                        title,
                        f"docName={metadata['docName']} category={metadata['category']} "
                        f"ipr={metadata['ipr']} submissionType={metadata['submissionType']}",
                    )
                )

    title = "candidate-approved XML and submission XML are the same bytes"
    candidate = authorization.get("publication_candidate")
    approved = candidate.get("authorized_xml_sha256") if isinstance(candidate, dict) else None
    repo_declared = authorized.get("sha256") if isinstance(authorized, dict) else None
    if not isinstance(approved, str) or not SHA256_RE.fullmatch(approved):
        results.append(_no("G14", title, "candidate authorized_xml_sha256 is missing or malformed"))
    elif approved != repo_declared:
        results.append(
            _no("G14", title, f"candidate {approved} != repository-declared {repo_declared}")
        )
    elif context.submission_xml_sha256 is None:
        results.append(_no("G14", title, "no submission XML digest was supplied"))
    elif context.submission_xml_sha256 != approved:
        results.append(
            _no("G14", title, f"submission {context.submission_xml_sha256} != authorized {approved}")
        )
    else:
        results.append(_ok("G14", title, f"sha256={approved}"))
    return results


def _check_workspace_and_build(context: GuardContext) -> list[CheckResult]:
    results: list[CheckResult] = []

    title = "no dirty or generated divergence exists"
    if context.workspace_clean is None:
        results.append(_no("G10", title, "workspace cleanliness was not observed"))
    elif not context.workspace_clean:
        results.append(_no("G10", title, "working tree has uncommitted or untracked changes"))
    else:
        results.append(_ok("G10", title, "working tree is clean"))

    title = "draft build and lint pass"
    build = context.build
    if build is None:
        results.append(_no("G11", title, "no build report was supplied"))
    elif not build.xml_parsed:
        results.append(_no("G11", title, "RFCXML did not parse"))
    elif not build.text_rendered:
        results.append(_no("G11", title, "plaintext rendering failed"))
    elif not build.html_rendered:
        results.append(_no("G11", title, "HTML rendering failed"))
    elif not build.lint_ran:
        results.append(_no("G11", title, "the draft linter did not run"))
    elif build.lint_status not in {"PASS", "PASS_WITH_WARNINGS"}:
        results.append(_no("G11", title, f"lint status {build.lint_status}"))
    else:
        versions = ", ".join(f"{name} {value}" for name, value in sorted(build.tool_versions.items()))
        results.append(_ok("G11", title, f"lint {build.lint_status}; {versions}"))
    return results


def _check_leaks(context: GuardContext) -> list[CheckResult]:
    results: list[CheckResult] = []

    # Artifacts are what a reader would receive, so a Publication Candidate
    # identifier inside one is a leak. The authorization record is the place
    # that identifier legitimately lives, so it is scanned under a rule that
    # permits it.
    artifacts: list[Path] = list(context.scan_paths)
    authorized = context.authorization.get("authorized_xml")
    if isinstance(authorized, dict) and isinstance(authorized.get("path"), str):
        candidate = context.repo_root / authorized["path"]
        if candidate.is_file():
            artifacts.append(candidate)
    artifacts = list(dict.fromkeys(artifacts))

    findings = scan_paths_for_leaks(artifacts)
    findings.extend(scan_paths_for_leaks([context.authorization_path], forbid_candidate_ids=False))
    private = [item for item in findings if "private marker" in item]
    secrets = [item for item in findings if "possible" in item]
    scanned = len(artifacts) + 1

    title = "no unpublished or private path is referenced"
    if private:
        results.append(_no("G12", title, "; ".join(sorted(set(private)))))
    else:
        results.append(_ok("G12", title, f"scanned {scanned} artifact(s)"))

    title = "no secret or private material enters artifacts"
    if secrets:
        results.append(_no("G13", title, "; ".join(sorted(set(secrets)))))
    else:
        results.append(_ok("G13", title, f"scanned {scanned} artifact(s)"))
    return results


def run_checks(context: GuardContext) -> GuardReport:
    """Run every guard check. Every non-PASS result blocks submission."""

    checks: list[CheckResult] = []
    checks.extend(_check_trigger(context))
    checks.extend(_check_tag_commit(context))
    checks.extend(_check_xml_identity(context))
    checks.extend(_check_authorization_shape(context))
    checks.extend(_check_candidate_identity(context))
    checks.extend(_check_workspace_and_build(context))
    checks.extend(_check_leaks(context))
    checks.sort(key=lambda check: check.check_id)
    return GuardReport(identity=_artifact_identity(context.authorization), checks=tuple(checks))


def build_context(
    repo_root: Path,
    authorization_path: Path,
    *,
    triggering_ref: str | None,
    submission_xml_sha256: str | None = None,
    build: BuildReport | None = None,
    scan_paths: Sequence[Path] = (),
    require_tag_signature: bool = True,
) -> GuardContext:
    """Load the authorization record and observe git for a real repository."""

    authorization = load_authorization(authorization_path)
    tag = None
    if triggering_ref and triggering_ref.startswith("refs/tags/"):
        tag = triggering_ref[len("refs/tags/") :]
    facts = collect_git_facts(repo_root, tag)
    return GuardContext(
        repo_root=repo_root,
        authorization=authorization,
        authorization_path=authorization_path,
        triggering_ref=triggering_ref,
        tag_commit=facts["tag_commit"],
        head_commit=facts["head_commit"],
        authorized_base_commits=facts["authorized_base_commits"],
        commit_on_authorized_state=facts["commit_on_authorized_state"],
        tag_is_annotated=facts["tag_is_annotated"],
        tag_signature_verified=facts["tag_signature_verified"],
        require_tag_signature=require_tag_signature,
        workspace_clean=facts["workspace_clean"],
        build=build,
        submission_xml_sha256=submission_xml_sha256,
        scan_paths=tuple(scan_paths),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--ref", dest="triggering_ref", default=None)
    parser.add_argument("--submission-xml", type=Path, default=None)
    parser.add_argument("--build-report", type=Path, default=None)
    parser.add_argument("--json", dest="json_out", type=Path, default=None)
    parser.add_argument(
        "--no-require-signature",
        action="store_true",
        help="only for local rehearsal of unsigned refs; CI never sets this",
    )
    args = parser.parse_args(argv)

    try:
        build: BuildReport | None = None
        if args.build_report is not None:
            raw = json.loads(args.build_report.read_text(encoding="utf-8"))
            build = BuildReport(
                xml_parsed=bool(raw.get("xml_parsed")),
                text_rendered=bool(raw.get("text_rendered")),
                html_rendered=bool(raw.get("html_rendered")),
                lint_ran=bool(raw.get("lint_ran")),
                lint_status=str(raw.get("lint_status", "NOT_RUN")),
                tool_versions=dict(raw.get("tool_versions") or {}),
                messages=tuple(raw.get("messages") or ()),
            )
        digest = sha256_file(args.submission_xml) if args.submission_xml else None
        context = build_context(
            args.repo_root.resolve(),
            args.authorization.resolve(),
            triggering_ref=args.triggering_ref,
            submission_xml_sha256=digest,
            build=build,
            require_tag_signature=not args.no_require_signature,
        )
    except (GuardError, OSError, json.JSONDecodeError) as exc:
        print(f"GUARD FAIL — {exc}", file=sys.stderr)
        return 1

    report = run_checks(context)
    for check in report.checks:
        print(f"{check.status}: {check.check_id} {check.title}: {check.detail}")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    if report.ok:
        print("GUARD PASS")
        return 0
    print(f"GUARD FAIL — {report.first_failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
