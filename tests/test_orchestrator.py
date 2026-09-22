from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from openocean_release.orchestrator import Orchestrator, publish_release
from openocean_release.runtime import sha256_file


ROOT = Path(__file__).resolve().parents[1]


class _Runner:
    def __init__(self, root: Path) -> None:
        self.root = root

    def storage(self, name: str) -> Path:
        if name != "releases":
            raise AssertionError(name)
        return self.root

    def credential_env(self, name: str) -> str:
        if name != "github_publish_token_env":
            raise AssertionError(name)
        return "TEST_GITHUB_TOKEN"


class AutomaticNotesTest(unittest.TestCase):
    def test_resume_id_cannot_escape_release_storage(self) -> None:
        orchestrator = object.__new__(Orchestrator)
        orchestrator.resume = "../outside"
        with self.assertRaisesRegex(RuntimeError, "YYYY.M.D.N"):
            orchestrator._select_version()

    def test_compares_with_latest_published_local_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            releases = Path(temporary)
            previous = releases / "2026.9.20.1"
            previous.mkdir()
            (previous / "state.json").write_text(
                json.dumps({"published": True}), encoding="utf-8")
            (previous / "release-lock.yaml").write_text(
                yaml.safe_dump({
                    "sources": {
                        "field_core": {
                            "repository": "OpenOceanAcoustic/OpenOcean-Field-Core",
                            "commit": "a" * 40,
                        }
                    }
                }),
                encoding="utf-8",
            )
            orchestrator = object.__new__(Orchestrator)
            orchestrator.release_id = "2026.9.21.1"
            orchestrator.runner = _Runner(releases)
            notes = orchestrator._automatic_notes({
                "sources": {
                    "field_core": {
                        "repository": "OpenOceanAcoustic/OpenOcean-Field-Core",
                        "commit": "b" * 40,
                    }
                }
            })
            self.assertIn("changes since v2026.9.20.1", notes)
            self.assertIn(f"{'a' * 40}...{'b' * 40}", notes)


class MatlabPreflightContractTest(unittest.TestCase):
    def test_preflight_does_not_require_graphics_or_desktop_experience(self) -> None:
        source = (ROOT / "openocean_release" / "orchestrator.py").read_text(
            encoding="utf-8")
        self.assertNotIn("imagesc", source)
        self.assertNotIn("InstallationType", source)
        self.assertNotIn("Desktop Experience", source)


class WindowsNativeToolchainContractTest(unittest.TestCase):
    def test_cmake_is_available_to_nested_windows_tests(self) -> None:
        source = (ROOT / "openocean_release" / "orchestrator.py").read_text(
            encoding="utf-8")
        self.assertIn(
            '$(Split-Path -Parent $cmake);$(Split-Path -Parent $ninja);',
            source)
        self.assertIn("VsDevCmd.bat", source)


class PublishVerificationTest(unittest.TestCase):
    def test_publish_id_cannot_escape_release_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, "YYYY.M.D.N"):
                publish_release("../outside", _Runner(Path(temporary)))

    def _sealed_release(self, releases: Path, release_id: str = "2026.9.21.1",
                        tag: str = "v{version}") -> Path:
        root = releases / release_id
        (root / "assets").mkdir(parents=True)
        config = {
            "schema": "openocean.release/v1",
            "release": {"version": release_id, "title": "Field {version}", "tag": tag},
            "sources": {},
            "products": {
                "native": {"enabled": False, "platforms": [], "families": []},
                "python": {"enabled": False, "platforms": [], "versions": []},
                "matlab": {"enabled": False},
                "field_runner": {"enabled": False},
            },
        }
        config_path = root / "release-config.yaml"
        config_path.write_text(yaml.safe_dump(config, sort_keys=True), encoding="utf-8")
        state = {
            "schema": "openocean.release-state/v1",
            "releaseId": release_id,
            "sealed": True,
            "tasks": {
                "resolve": {
                    "status": "succeeded", "inputSha256": "0" * 64,
                    "outputs": {},
                }
            },
        }
        (root / "state.json").write_text(
            json.dumps(state), encoding="utf-8")
        summary = {
            "schema": "openocean.release-test-summary/v1",
            "releaseId": release_id,
            "status": "passed",
            "failed": [],
            "tasks": {"resolve": {"status": "succeeded"}},
        }
        summary_path = root / "test-summary.json"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps({
            "schema": "openocean.release-manifest/v1",
            "releaseId": release_id,
            "files": [],
        }), encoding="utf-8")
        lock_path = root / "release-lock.yaml"
        lock_path.write_text(yaml.safe_dump({
            "schema": "openocean.release-lock/v1",
            "releaseId": release_id,
            "configSha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "orchestrator": {
                "repository": "OpenOceanAcoustic/OpenOcean-Release",
                "commit": "a" * 40,
            },
            "sources": {},
            "matrix": {
                "nativePlatforms": [], "pythonPlatforms": [],
                "pythonVersions": [], "matlabPlatform": None,
                "fieldRunnerBackends": [],
            },
        }), encoding="utf-8")
        notes_path = root / "release-notes.md"
        notes_path.write_text("release notes\n", encoding="utf-8")
        # release-notes.md is the Release body, not an uploaded asset, so it is
        # deliberately outside the checksum set. release-config.yaml is inside it:
        # the lock publishes configSha256 and consumers need the file to verify it.
        checksum_paths = (config_path, lock_path, manifest_path, summary_path)
        (root / "SHA256SUMS").write_text("".join(
            f"{sha256_file(path)}  {path.name}\n" for path in checksum_paths),
            encoding="utf-8")
        return root

    def test_publish_uses_the_tag_from_the_sealed_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            releases = Path(temporary)
            root = self._sealed_release(releases, "1.0.0", "OpenOcean-Field-V{version}")
            with mock.patch.dict(os.environ, {"TEST_GITHUB_TOKEN": "token"}), \
                    mock.patch("openocean_release.orchestrator.create_public_release") as create:
                publish_release("1.0.0", _Runner(releases))
                self.assertEqual(create.call_args.kwargs["tag"], "OpenOcean-Field-V1.0.0")
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["publishedTag"], "OpenOcean-Field-V1.0.0")

    def test_publish_rechecks_the_complete_sealed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            releases = Path(temporary)
            root = self._sealed_release(releases)
            runner = _Runner(releases)
            with mock.patch.dict(os.environ, {"TEST_GITHUB_TOKEN": "token"}), \
                    mock.patch(
                        "openocean_release.orchestrator.create_public_release"
                    ) as create:
                publish_release("2026.9.21.1", runner)
                create.assert_called_once()
            state_path = root / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"]["unexpected"] = {
                "status": "succeeded", "inputSha256": "1" * 64,
                "outputs": {},
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "task set"):
                publish_release("2026.9.21.1", runner)

    def test_publish_rejects_modified_release_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            releases = Path(temporary)
            root = self._sealed_release(releases)
            # Corrupt one recorded digest while keeping the file-name set
            # intact, so the per-file comparison is what rejects it. Editing the
            # config instead would be caught earlier by the lock's configSha256.
            checksums_path = root / "SHA256SUMS"
            lines = checksums_path.read_text(encoding="utf-8").splitlines(True)
            lines[-1] = "0" * 64 + lines[-1][64:]
            checksums_path.write_text("".join(lines), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "SHA256SUMS mismatch"):
                publish_release("2026.9.21.1", _Runner(releases))


if __name__ == "__main__":
    unittest.main()
