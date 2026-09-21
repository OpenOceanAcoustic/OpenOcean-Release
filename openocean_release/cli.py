"""Command-line interface for local and self-hosted release runs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import pwd
import sys

from .config import ConfigurationError, ReleaseConfig, RunnerConfig, parse_ref_overrides
from .orchestrator import Orchestrator, publish_release


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Build and publish OpenOcean Field releases")
    result.add_argument("command", nargs="?", choices=("build", "preflight", "publish"), default="build")
    result.add_argument("-c", "--config", type=Path, help="public release YAML")
    result.add_argument("--runner-config", type=Path, help="private runner YAML; defaults to OPENOCEAN_RUNNER_CONFIG")
    result.add_argument("--profile", choices=("full", "native", "python", "matlab"))
    result.add_argument("--version", help="override auto release version")
    result.add_argument("--ref", action="append", default=[], metavar="SOURCE=REF")
    result.add_argument("--resume", help="resume an existing release ID")
    result.add_argument("--rebuild", action="append", default=[], metavar="TASK")
    result.add_argument("--release-id", help="sealed release to publish")
    return result


def _release_config(arguments: argparse.Namespace) -> ReleaseConfig:
    if arguments.config is None:
        raise ConfigurationError("build and preflight require -c/--config")
    return ReleaseConfig.load(
        arguments.config,
        profile_override=arguments.profile,
        version_override=arguments.version,
        ref_overrides=parse_ref_overrides(arguments.ref),
    )


def _maybe_reexec_as_build_user(arguments: argparse.Namespace, runner: RunnerConfig) -> None:
    execution = runner.section("execution")
    build_user = execution.get("build_user")
    if not execution.get("require_initial_sudo", False) or not isinstance(build_user, str):
        return
    if pwd.getpwuid(os.geteuid()).pw_name == build_user:
        return
    preserve = [
        "OPENOCEAN_RUNNER_CONFIG", "OOA_FIELD_READ_TOKEN", "GH_TOKEN",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    ]
    command = [
        "sudo", "-H", "-u", build_user,
        "--preserve-env=" + ",".join(preserve),
        sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"),
        *sys.argv[1:],
    ]
    os.execvp("sudo", command)


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        runner = RunnerConfig.load(arguments.runner_config)
        if arguments.command == "publish":
            if not arguments.release_id:
                raise ConfigurationError("publish requires --release-id")
            _maybe_reexec_as_build_user(arguments, runner)
            release = None
            if arguments.config is not None:
                release = ReleaseConfig.load(
                    arguments.config,
                    profile_override=arguments.profile,
                    version_override=arguments.version,
                    ref_overrides=parse_ref_overrides(arguments.ref),
                )
            publish_release(arguments.release_id, runner, config=release)
            print(f"published OpenOcean Field {arguments.release_id}")
            return 0
        release = _release_config(arguments)
        _maybe_reexec_as_build_user(arguments, runner)
        orchestrator = Orchestrator(
            release, runner, resume=arguments.resume, rebuild=arguments.rebuild
        )
        if arguments.command == "preflight":
            orchestrator.preflight()
            return 0
        release_id = orchestrator.build()
        print(f"release build complete: {release_id}")
        return 0
    except (ConfigurationError, RuntimeError, OSError) as error:
        print(f"openocean-release: {error}", file=sys.stderr)
        return 2
