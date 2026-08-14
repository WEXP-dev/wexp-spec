"""Shared fixtures for publication-pipeline tests.

Nothing here contacts the network, and no fixture ever enables a live
submission switch.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import publication_guard as guard  # noqa: E402

DUMMY_COMMIT = "1" * 40
DUMMY_BASE_COMMIT = "1" * 40

MINIMAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rfc ipr="trust200902" docName="{identity}" category="info" submissionType="IETF">
  <front>
    <title abbrev="Test">Test Draft</title>
    <author initials="A." surname="Author" fullname="A Author">
      <address><email>author@example.com</email></address>
    </author>
    <date year="2026" month="August" day="14"/>
    <abstract><t>Fixture.</t></abstract>
  </front>
  <middle><section><name>Body</name><t>Fixture body.</t></section></middle>
  <back/>
</rfc>
"""


def write_xml(root: Path, identity: str, *, body: str | None = None) -> Path:
    """Write a syntactically valid RFCXML fixture and return its path."""

    target = root / "drafts" / "core" / identity[-2:] / f"{identity}.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body if body is not None else MINIMAL_XML.format(identity=identity), encoding="utf-8")
    return target


def sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authorization_dict(root: Path, identity: str, xml_path: Path, **overrides: Any) -> dict[str, Any]:
    digest = sha256_text(xml_path)
    record: dict[str, Any] = {
        "schema_version": 1,
        "record_kind": guard.PUBLICATION_AUTHORIZATION,
        "authorization_id": "PA-core-01-001",
        "draft_name": identity.rsplit("-", 1)[0],
        "revision": identity.rsplit("-", 1)[1],
        "artifact_identity": identity,
        "publication_tag": identity,
        "expected_submission_type": "IETF",
        "publication_candidate": {
            "candidate_id": "PC-core-01-001",
            "source_workspace": "wexp-prepublication-workspace",
            "source_commit": "a" * 40,
            "candidate_tree_sha256": "b" * 64,
            "authorized_xml_sha256": digest,
        },
        "authorized_xml": {
            "path": xml_path.relative_to(root).as_posix(),
            "sha256": digest,
        },
        "authorized_by": {
            "identity": "WEXP publication authority",
            "method": "signed publication tag",
            "date": "2026-08-14T00:00:00Z",
        },
        "submission": {
            "enabled": True,
            "datatracker_user": "author@example.com",
            "replaces": [],
        },
    }
    record.update(overrides)
    return record


def write_authorization(root: Path, record: dict[str, Any]) -> Path:
    target = root / "publication" / "authorizations" / f"{record['artifact_identity']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return target


def passing_build() -> guard.BuildReport:
    return guard.BuildReport(
        xml_parsed=True,
        text_rendered=True,
        html_rendered=True,
        lint_ran=True,
        lint_status="PASS_WITH_WARNINGS",
        tool_versions={"xml2rfc": "3.34.0", "idnits": "3.1.0"},
    )


def passing_context(root: Path, identity: str = "draft-example-wexp-core-01", **overrides: Any) -> guard.GuardContext:
    """A GuardContext in which every check passes, for negative-test mutation.

    Supplying ``authorization`` suppresses fixture regeneration so that a test
    can mutate the on-disk artifacts first and have the guard observe them.
    """

    record = overrides.pop("authorization", None)
    if record is None:
        xml_path = write_xml(root, identity)
        record = authorization_dict(root, identity, xml_path)
        authorization_path = write_authorization(root, record)
    else:
        xml_path = root / record["authorized_xml"]["path"]
        authorization_path = overrides.pop("authorization_path", None) or write_authorization(root, record)
    defaults: dict[str, Any] = {
        "repo_root": root,
        "authorization": record,
        "authorization_path": authorization_path,
        "triggering_ref": f"refs/tags/{identity}",
        "tag_commit": DUMMY_COMMIT,
        "head_commit": DUMMY_COMMIT,
        "authorized_base_commits": (DUMMY_BASE_COMMIT,),
        "commit_on_authorized_state": True,
        "tag_is_annotated": True,
        "tag_signature_verified": True,
        "require_tag_signature": True,
        "workspace_clean": True,
        "build": passing_build(),
        "submission_xml_sha256": sha256_text(xml_path) if xml_path.is_file() else None,
        "scan_paths": (xml_path,) if xml_path.is_file() else (),
    }
    defaults.update(overrides)
    return guard.GuardContext(**defaults)
