from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_publication import verify_manifest  # noqa: E402


class PublicationManifestTest(unittest.TestCase):
    def test_core_00_manifest_verifies(self) -> None:
        verified = verify_manifest(ROOT / "manifests" / "core-00.json")
        self.assertEqual(len(verified), 3)
        self.assertTrue(verified[0].endswith(".xml"))


if __name__ == "__main__":
    unittest.main()
