from __future__ import annotations

import unittest

from openocean_release.cli import parser


class CliTest(unittest.TestCase):
    def test_config_before_publish_command_is_supported(self) -> None:
        arguments = parser().parse_args([
            "-c", "release.yaml", "publish", "--release-id", "2026.9.20.1"
        ])
        self.assertEqual(arguments.command, "publish")
        self.assertEqual(arguments.release_id, "2026.9.20.1")

    def test_omitted_command_defaults_to_build(self) -> None:
        arguments = parser().parse_args(["-c", "release.yaml"])
        self.assertEqual(arguments.command, "build")


if __name__ == "__main__":
    unittest.main()
