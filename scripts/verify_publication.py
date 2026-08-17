#!/usr/bin/env python3
"""Verify file hashes and XML syntax declared by WEXP publication manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        fail(f"{path}: top-level JSON value must be an object")
    return value


def resolve_repo_path(relative: str) -> Path:
    candidate = (ROOT / relative).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"artifact path escapes repository: {relative}") from exc
    return candidate


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# A manifest describes either a specification this repository imported after
# someone else published it, or one this repository published itself. The two
# make different provenance claims, so each carries its own required fields and
# neither set may be satisfied by the other's evidence.
HISTORICAL_IMPORT = "historical_import"
WEXP_PUBLICATION = "wexp_publication"

COMMON_FIELDS = {
    "artifact_identity",
    "revision",
    "publication_status",
    "provenance",
    "integrity_scope",
    "artifacts",
}


def verify_manifest(path: Path) -> list[str]:
    manifest = load_json(path)
    status = manifest.get("publication_status")
    if status not in (HISTORICAL_IMPORT, WEXP_PUBLICATION):
        fail(
            f"{path}: publication_status must be {HISTORICAL_IMPORT!r} or "
            f"{WEXP_PUBLICATION!r}, not {status!r}"
        )
    extra = {"repository_import"} if status == HISTORICAL_IMPORT else {"freeze"}
    missing = sorted((COMMON_FIELDS | extra) - manifest.keys())
    if missing:
        fail(f"{path}: missing fields: {', '.join(missing)}")

    provenance = manifest["provenance"]
    if not isinstance(provenance, dict):
        fail(f"{path}: provenance must be an object")
    record = provenance.get("wexp_publication_record")
    if status == HISTORICAL_IMPORT:
        if record != "unavailable":
            fail(f"{path}: historical import must record unavailable WEXP publication record")
    else:
        # A self-published specification must name the exact authorization it was
        # published under. "unavailable" is the historical-import answer and would
        # silently understate the provenance this class is required to carry.
        if not isinstance(record, str) or not record.strip() or record == "unavailable":
            fail(f"{path}: WEXP publication must name its publication record")
        freeze = manifest["freeze"]
        if not isinstance(freeze, dict) or not isinstance(freeze.get("identity"), str):
            fail(f"{path}: WEXP publication must declare freeze.identity")
        frozen = freeze.get("xml_sha256")
        if not isinstance(frozen, str) or not re.fullmatch(r"[0-9a-f]{64}", frozen):
            fail(f"{path}: freeze.xml_sha256 must be 64 lowercase hexadecimal characters")
        declared = {
            entry.get("sha256")
            for entry in manifest["artifacts"]
            if isinstance(entry, dict) and str(entry.get("path", "")).endswith(".xml")
        }
        if frozen not in declared:
            fail(f"{path}: no declared XML artifact matches freeze.xml_sha256 {frozen}")

    if manifest["integrity_scope"] != "current_repository_bytes":
        fail(f"{path}: integrity scope must not imply original-publication proof")

    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        fail(f"{path}: artifacts must be a non-empty array")
    seen: set[str] = set()
    verified: list[str] = []
    for entry in artifacts:
        if not isinstance(entry, dict):
            fail(f"{path}: artifact entries must be objects")
        relative = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            fail(f"{path}: artifact path and sha256 must be strings")
        if relative in seen:
            fail(f"{path}: duplicate artifact path: {relative}")
        seen.add(relative)
        artifact = resolve_repo_path(relative)
        if not artifact.is_file():
            fail(f"{path}: declared artifact does not exist: {relative}")
        actual = sha256(artifact)
        if actual != expected:
            fail(f"{path}: SHA-256 mismatch for {relative}: {actual} != {expected}")
        if artifact.suffix == ".xml":
            ET.parse(artifact)
        verified.append(relative)
    return verified


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifests",
        nargs="*",
        type=Path,
        default=sorted((ROOT / "manifests").glob("*.json")),
        help="manifest files to verify (default: all JSON files under manifests/)",
    )
    args = parser.parse_args()
    if not args.manifests:
        print("FAIL: no publication manifests found", file=sys.stderr)
        return 1
    try:
        count = 0
        for manifest in args.manifests:
            files = verify_manifest(manifest.resolve())
            count += len(files)
            print(f"PASS: {manifest}: verified {len(files)} artifact(s)")
        print(f"PASS: verified {len(args.manifests)} manifest(s), {count} artifact(s)")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
