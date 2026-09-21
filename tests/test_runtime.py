from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from openocean_release.runtime import EventLogger, TaskState, sha256_file


class RuntimeTest(unittest.TestCase):
    def test_task_resume_requires_matching_input_and_output_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = TaskState.open(root / "state.json", "2026.9.20.1")
            output = root / "asset.zip"
            output.write_bytes(b"first")
            state.start("linux.native.core", "input-one")
            state.succeed("linux.native.core", [output])
            self.assertTrue(state.reusable("linux.native.core", "input-one", [output]))
            output.write_bytes(b"changed")
            self.assertFalse(state.reusable("linux.native.core", "input-one", [output]))
            self.assertFalse(state.reusable("linux.native.core", "input-two", [output]))

    def test_logger_redacts_secrets_from_all_persistent_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = EventLogger(root, ["private-token"])
            logger.event("test", "INFO", "value=private-token")
            self.assertNotIn("private-token", (root / "events.jsonl").read_text())
            self.assertNotIn("private-token", (root / "summary.log").read_text())

    def test_logger_redacts_proxy_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = EventLogger(root)
            logger.event(
                "proxy", "INFO",
                "using https://release-user:private-password@proxy.example:7890")
            persisted = (root / "events.jsonl").read_text()
            self.assertNotIn("release-user", persisted)
            self.assertNotIn("private-password", persisted)
            self.assertIn("https://***@proxy.example:7890", persisted)

    def test_logger_redacts_structured_event_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = EventLogger(root, ["private-token"])
            logger.event(
                "test", "INFO", "structured field",
                context={"credential": "private-token"},
            )
            self.assertNotIn(
                "private-token", (root / "events.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()
