from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from openocean_release.config import BACKENDS, ConfigurationError, ReleaseConfig, release_tag
from openocean_release.defaults import release_document


ROOT = Path(__file__).resolve().parents[1]


def legacy_document() -> dict:
    document = release_document()
    document["release"].update(version="1.0.0", notes="docs/releases/openocean-field-v1.0.0.md")
    return document


def load_legacy(**overrides) -> ReleaseConfig:
    return ReleaseConfig.load(ROOT / "main.py", document_override=legacy_document(), **overrides)


class ReleaseConfigTest(unittest.TestCase):
    def test_legacy_full_config_has_atomic_ten_backend_matrix(self) -> None:
        config = load_legacy()
        self.assertEqual(config.profile, "full")
        self.assertTrue(config.products.native)
        self.assertTrue(config.products.python)
        self.assertTrue(config.products.matlab)
        self.assertEqual(config.matlab_test_release, "R2025b")
        self.assertEqual(len(BACKENDS), 10)
        self.assertEqual(config.python_versions, ("cp310", "cp311", "cp312", "cp313", "cp314"))

    def test_semantic_version_and_requested_tag(self) -> None:
        config = load_legacy()
        self.assertEqual(config.version, "1.0.0")
        self.assertEqual(release_tag(config.document["release"]["tag"], config.version),
                         "OpenOcean-Field-V1.0.0")
        self.assertEqual(config.native_platforms, ("windows-x86_64",))
        self.assertEqual(len(config.native_families) + len(config.python_platforms) + 1, 9)
        self.assertEqual(release_tag("v{version}", "2026.9.23.1"), "v2026.9.23.1")

    def test_tag_rejects_unsafe_names_and_unknown_placeholders(self) -> None:
        for template in ("../{version}", "{missing}", "{version.__class__}",
                         "-tag", "tag.lock", "tag..suffix", "tag/branch", "{version!r}"):
            with self.subTest(template=template), self.assertRaises(ConfigurationError):
                release_tag(template, "1.0.0")

    def test_command_line_profile_is_stronger_than_file_product_flags(self) -> None:
        config = load_legacy(profile_override="python")
        self.assertFalse(config.products.native)
        self.assertTrue(config.products.python)
        self.assertFalse(config.products.matlab)
        self.assertTrue(config.products.field_runner)

    def test_required_adapter_cannot_be_disabled(self) -> None:
        document = legacy_document()
        document["sources"]["wi"]["enabled"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.yaml"
            document["release"]["notes"] = "auto"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "required sources are disabled"):
                ReleaseConfig.load(path)

    def test_backend_subset_is_rejected(self) -> None:
        document = legacy_document()
        document["products"]["field_runner"]["backends"].pop()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.yaml"
            document["release"]["notes"] = "auto"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "fixed ten-backend"):
                ReleaseConfig.load(path)

    def test_python_platform_can_be_selected_but_abi_matrix_stays_fixed(self) -> None:
        config = load_legacy(targets=("linux-python",))
        self.assertEqual(config.python_platforms, ("linux-x86_64",))
        self.assertEqual(config.document["products"]["python"]["platforms"], ["linux-x86_64"])
        document = legacy_document()
        document["products"]["python"]["versions"] = ["cp310", "cp311"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.yaml"
            document["release"]["notes"] = "auto"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "requires cp310 through cp314"):
                ReleaseConfig.load(path)

    def test_native_family_subset_is_allowed(self) -> None:
        document = legacy_document()
        document["products"]["native"]["families"] = ["pe"]
        document["products"]["python"]["enabled"] = False
        document["products"]["matlab"]["enabled"] = False
        document["products"]["field_runner"]["enabled"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.yaml"
            document["release"]["notes"] = "auto"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            config = ReleaseConfig.load(path)
            self.assertEqual(config.native_families, ("pe",))

    def test_inline_notes_override_old_notes_path(self) -> None:
        config = load_legacy(notes_text_override="# New notes\n")
        self.assertEqual(config.notes, "auto")
        self.assertEqual(config.notes_text, "# New notes\n")
        self.assertEqual(config.document["release"]["notes"], "auto")

    def test_unknown_source_is_rejected(self) -> None:
        document = legacy_document()
        document["sources"]["unreviewed_model"] = {
            "repository": "example/unreviewed",
            "ref": "main",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.yaml"
            document["release"]["notes"] = "auto"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "unknown fields"):
                ReleaseConfig.load(path)

    def test_release_notes_cannot_escape_the_config_repository(self) -> None:
        document = legacy_document()
        document["release"]["notes"] = "../private-notes.md"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "release.yaml"
            path.parent.mkdir()
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "inside the config repository"):
                ReleaseConfig.load(path)


if __name__ == "__main__":
    unittest.main()
