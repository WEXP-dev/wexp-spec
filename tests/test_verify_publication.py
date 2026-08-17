from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_publication import verify_manifest  # noqa: E402


class PublicationManifestTest(unittest.TestCase):
    def test_core_00_manifest_verifies(self) -> None:
        verified = verify_manifest(ROOT / "manifests" / "core-00.json")
        self.assertEqual(len(verified), 3)
        self.assertTrue(verified[0].endswith(".xml"))

    def test_core_01_manifest_verifies(self) -> None:
        verified = verify_manifest(ROOT / "manifests" / "core-01.json")
        self.assertEqual(len(verified), 3)
        self.assertTrue(verified[0].endswith(".xml"))


class MutatedManifestTest(unittest.TestCase):
    """Each mutation must be rejected. A manifest class that can be satisfied by
    the other class's evidence would let a self-published specification claim the
    weaker provenance of an import, or the reverse."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)

    def _write(self, source: str, mutate) -> Path:
        manifest = json.loads((ROOT / "manifests" / source).read_text(encoding="utf-8"))
        mutate(manifest)
        target = self.directory / "manifest.json"
        target.write_text(json.dumps(manifest), encoding="utf-8")
        return target

    def _rejects(self, source: str, mutate) -> None:
        with self.assertRaises(ValueError):
            verify_manifest(self._write(source, mutate))

    def test_unknown_publication_status_is_rejected(self) -> None:
        self._rejects("core-01.json", lambda m: m.__setitem__("publication_status", "something_else"))

    def test_wexp_publication_may_not_claim_unavailable_record(self) -> None:
        self._rejects(
            "core-01.json",
            lambda m: m["provenance"].__setitem__("wexp_publication_record", "unavailable"),
        )

    def test_wexp_publication_requires_freeze(self) -> None:
        self._rejects("core-01.json", lambda m: m.pop("freeze"))

    def test_freeze_digest_must_match_a_declared_xml_artifact(self) -> None:
        self._rejects("core-01.json", lambda m: m["freeze"].__setitem__("xml_sha256", "0" * 64))

    def test_freeze_digest_must_be_lowercase_hex(self) -> None:
        self._rejects("core-01.json", lambda m: m["freeze"].__setitem__("xml_sha256", "NOT-A-DIGEST"))

    def test_historical_import_still_requires_unavailable_record(self) -> None:
        self._rejects(
            "core-00.json",
            lambda m: m["provenance"].__setitem__("wexp_publication_record", "PC-core-00-001"),
        )

    def test_historical_import_still_requires_repository_import(self) -> None:
        self._rejects("core-00.json", lambda m: m.pop("repository_import"))

    def test_integrity_scope_is_still_enforced(self) -> None:
        self._rejects(
            "core-01.json",
            lambda m: m.__setitem__("integrity_scope", "original_publication_proof"),
        )


if __name__ == "__main__":
    unittest.main()
