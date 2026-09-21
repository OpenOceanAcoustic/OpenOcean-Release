from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import yaml

from openocean_release.config import BACKENDS, ConfigurationError, ReleaseConfig


ROOT = Path(__file__).resolve().parents[1]


class ReleaseConfigTest(unittest.TestCase):
    def test_checked_in_config_has_atomic_eight_backend_matrix(self) -> None:
        config = ReleaseConfig.load(ROOT / "release.yaml")
        self.assertEqual(config.profile, "full")
        self.assertTrue(config.products.native)
        self.assertTrue(config.products.python)
        self.assertTrue(config.products.matlab)
        self.assertEqual(config.matlab_test_release, "R2025b")
        self.assertEqual(len(BACKENDS), 8)
        self.assertEqual(config.python_versions, ("cp310", "cp311", "cp312", "cp313", "cp314"))

    def test_command_line_profile_is_stronger_than_file_product_flags(self) -> None:
        config = ReleaseConfig.load(ROOT / "release.yaml", profile_override="python")
        self.assertFalse(config.products.native)
        self.assertTrue(config.products.python)
        self.assertFalse(config.products.matlab)
        self.assertTrue(config.products.field_runner)

    def test_future_adapter_cannot_be_enabled(self) -> None:
        document = yaml.safe_load((ROOT / "release.yaml").read_text(encoding="utf-8"))
        document["sources"]["wi"]["enabled"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.yaml"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "release adapter not implemented"):
                ReleaseConfig.load(path)

    def test_backend_subset_is_rejected(self) -> None:
        document = yaml.safe_load((ROOT / "release.yaml").read_text(encoding="utf-8"))
        document["products"]["field_runner"]["backends"].pop()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.yaml"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "fixed eight-backend"):
                ReleaseConfig.load(path)

    def test_python_platform_and_abi_matrix_is_atomic(self) -> None:
        cases = (
            ("platforms", ["linux-x86_64"], "requires Linux and Windows"),
            ("versions", ["cp310", "cp311", "cp312", "cp313"],
             "requires cp310 through cp314"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                document = yaml.safe_load(
                    (ROOT / "release.yaml").read_text(encoding="utf-8"))
                document["products"]["python"][field] = value
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "release.yaml"
                    path.write_text(yaml.safe_dump(document), encoding="utf-8")
                    with self.assertRaisesRegex(ConfigurationError, message):
                        ReleaseConfig.load(path)

    def test_unknown_source_is_rejected(self) -> None:
        document = yaml.safe_load((ROOT / "release.yaml").read_text(encoding="utf-8"))
        document["sources"]["unreviewed_model"] = {
            "repository": "example/unreviewed",
            "ref": "main",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.yaml"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "unknown fields"):
                ReleaseConfig.load(path)

    def test_release_notes_cannot_escape_the_config_repository(self) -> None:
        document = yaml.safe_load((ROOT / "release.yaml").read_text(encoding="utf-8"))
        document["release"]["notes"] = "../private-notes.md"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "release.yaml"
            path.parent.mkdir()
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "inside the config repository"):
                ReleaseConfig.load(path)


if __name__ == "__main__":
    unittest.main()
