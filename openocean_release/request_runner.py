"""Validate an Actions request and execute it with the server's private runner."""

from __future__ import annotations

from copy import deepcopy
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

import yaml

from .config import ConfigurationError, ReleaseConfig, RunnerConfig
from .github import GitHub
from .orchestrator import Orchestrator, publish_release
from .plan import config_for_request, validate_request

CI_WORKFLOWS = {
    "field_core": ("ci.yml",),
    "ray_mode": ("ci.yml", "tests.yml"),
    "normal_mode": ("ci.yml", "tests.yml"),
    "pe": ("ci.yml", "tests.yml"),
    "toolbox": ("ci.yml",),
    "wi": ("ci.yml", "tests.yml"),
    "couple": ("ci.yml", "tests.yml"),
}


def _actor() -> str:
    actor = os.environ.get("GITHUB_TRIGGERING_ACTOR") or os.environ.get("GITHUB_ACTOR", "")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", actor):
        raise ConfigurationError("Actions did not provide a valid triggering actor")
    return actor


def verify_sources(config: ReleaseConfig, github: GitHub, actor: str, *, check_ci: bool) -> ReleaseConfig:
    document = deepcopy(config.document)
    checks: dict[str, Any] = {}
    for name, source in config.sources.items():
        if not source.enabled:
            continue
        if not source.repository.startswith("OpenOceanAcoustic/"):
            raise ConfigurationError("source repository is outside OpenOceanAcoustic")
        github.require_read_permission(source.repository, actor)
        sha = github.resolve_ref(source.repository, source.ref)
        workflow_runs = {
            workflow: github.successful_workflow_run(source.repository, workflow, sha)
            for workflow in CI_WORKFLOWS[name]
        } if check_ci else {}
        checks[name] = {"repository": source.repository, "requestedRef": source.ref,
                        "sha": sha, "workflows": workflow_runs}
        document["sources"][name]["ref"] = sha
    document["verification"] = {"actor": actor, "sources": checks,
                                "ciRequired": check_ci}
    return ReleaseConfig.load(config.path, document_override=document)


def _preview_runner(runner: RunnerConfig, run_id: str) -> RunnerConfig:
    if not re.fullmatch(r"[1-9][0-9]{0,19}", run_id):
        raise ConfigurationError("GITHUB_RUN_ID must be numeric")
    document = deepcopy(runner.document)
    preview_root = runner.storage("root") / "previews"
    preview_root.mkdir(parents=True, exist_ok=True)
    cutoff = dt.datetime.now().timestamp() - 7 * 86400
    for entry in preview_root.iterdir():
        if entry.is_dir() and re.fullmatch(r"[1-9][0-9]{0,19}", entry.name) and entry.stat().st_mtime < cutoff:
            shutil.rmtree(entry)
    document["storage"]["releases"] = str(preview_root / run_id)
    return RunnerConfig(runner.path, document)


def _summary(directory: Path) -> str:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    lines = [f"Sealed directory: {directory}", "Files and SHA256:"]
    for item in manifest["files"]:
        lines.append(f"- {directory / 'assets' / item['path']}  {item['sha256']}")
    result = "\n".join(lines)
    print(result)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            summary.write("## OpenOcean build results\n\n```text\n" + result + "\n```\n")
    return result


def run_request(kind: str, raw_request: str, *, stage: str = "build") -> str:
    request = validate_request(json.loads(raw_request), kind)
    runner = RunnerConfig.load()
    read_env = runner.credential_env("source_read_token_env")
    token = os.environ.get(read_env)
    if not token:
        raise ConfigurationError(f"Actions secret {read_env} is missing")
    github = GitHub(token)
    actor = _actor()
    if stage == "publish" or not request["build"]:
        release_id = request["release_id"] or os.environ.get("OPENOCEAN_SEALED_RELEASE_ID", "")
        snapshot = yaml.safe_load((runner.storage("releases") / release_id / "release-config.yaml").read_text(encoding="utf-8"))
        for name, source in snapshot["sources"].items():
            if source.get("enabled", True):
                github.require_read_permission(source["repository"], actor)
        if stage == "publish":
            if not request["publish"] or kind != "release":
                raise ConfigurationError("publication was not explicitly enabled")
            publish_release(release_id, runner)
        return release_id
    config = config_for_request(request, kind)
    if kind == "preview":
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        runner = _preview_runner(runner, run_id)
        if request["version"] == "auto":
            today = dt.datetime.now().astimezone()
            document = deepcopy(config.document)
            document["release"]["version"] = f"{today.year}.{today.month}.{today.day}.{run_id}"
            config = ReleaseConfig.load(config.path, document_override=document)
    config = verify_sources(config, github, actor, check_ci=(kind == "release"))
    release_id = Orchestrator(config, runner).build()
    _summary(runner.storage("releases") / release_id)
    return release_id
