"""Command-line interface for local and self-hosted release runs."""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import pwd
import sys

from .config import (
    ConfigurationError,
    ReleaseConfig,
    RunnerConfig,
    parse_ref_overrides,
    parse_targets,
)
from .orchestrator import Orchestrator, publish_release


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Build and publish OpenOcean Field releases")
    result.add_argument("command", nargs="?", choices=("plan", "build", "preflight", "publish"), default="build")
    result.add_argument("-c", "--config", type=Path, help="public release YAML")
    result.add_argument("--runner-config", type=Path, help="private runner YAML; defaults to OPENOCEAN_RUNNER_CONFIG")
    result.add_argument("--profile", choices=("full", "native", "python", "matlab", "custom"))
    result.add_argument(
        "--target", action="append", default=[], metavar="TARGET",
        help="package only the named component; repeatable. One of: "
             "linux-native, windows-native, linux-python, windows-python, matlab")
    result.add_argument("--version", help="override auto release version")
    result.add_argument("--notes-text", help="Markdown release body to seal with the build")
    result.add_argument("--ref", action="append", default=[], metavar="SOURCE=REF")
    result.add_argument("--resume", help="resume an existing release ID")
    result.add_argument("--rebuild", action="append", default=[], metavar="TASK")
    result.add_argument("--release-id", help="sealed release to publish")
    return result


def _release_config(arguments: argparse.Namespace) -> ReleaseConfig:
    if arguments.config is None:
        raise ConfigurationError("plan, preflight, and build require -c/--config")
    return ReleaseConfig.load(
        arguments.config,
        profile_override=arguments.profile,
        version_override=arguments.version,
        notes_text_override=arguments.notes_text,
        ref_overrides=parse_ref_overrides(arguments.ref),
        targets=parse_targets(arguments.target),
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


def _require_credential(runner: RunnerConfig, key: str, operation: str) -> None:
    name = runner.credential_env(key)
    if os.environ.get(name):
        return
    if not sys.stdin.isatty():
        raise ConfigurationError(f"{operation} requires {name}; set it in the environment")
    value = getpass.getpass(f"{operation}: enter {name} (input hidden): ")
    if not value:
        raise ConfigurationError(f"{name} cannot be empty")
    os.environ[name] = value


def _print_plan(release: ReleaseConfig, runner: RunnerConfig) -> None:
    print(f"Version: {release.version}")
    print(f"Native families: {', '.join(release.native_families) if release.products.native else 'off'}")
    print(f"Native platforms: {', '.join(release.native_platforms) if release.products.native else 'off'}")
    print(f"Python platforms: {', '.join(release.python_platforms) if release.products.python else 'off'}")
    print(f"MATLAB: {'on' if release.products.matlab else 'off'}")
    print("Source refs:")
    for name, source in release.sources.items():
        print(f"  {name}: {source.ref}")
    print("Storage paths:")
    for name in ("root", "linux", "windows", "cache", "staging", "releases"):
        print(f"  {name}: {runner.storage(name)}")
    windows = runner.section("windows")
    print(f"Windows host root: {windows.get('shared_host_root')}")
    print(f"Windows VM root: {windows.get('shared_guest_root')}")
    print("Credentials (values are never displayed):")
    for key in ("source_read_token_env", "github_publish_token_env"):
        name = runner.credential_env(key)
        print(f"  {name}: {'set' if os.environ.get(name) else 'will be prompted when needed'}")
    if release.notes_text is not None:
        print("Release notes:\n" + release.notes_text)
    else:
        print(f"Release notes: {release.notes}")
    print("Plan only; no source refs were resolved or builds started.")


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        runner = RunnerConfig.load(arguments.runner_config)
        if arguments.command == "publish":
            if arguments.notes_text is not None:
                raise ConfigurationError("publish uses sealed release notes; provide --notes-text during build")
            if not arguments.release_id:
                raise ConfigurationError("publish requires --release-id")
            _require_credential(runner, "github_publish_token_env", "publish")
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
        if arguments.command == "plan":
            _print_plan(release, runner)
            return 0
        _require_credential(runner, "source_read_token_env", arguments.command)
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
