"""Minimal authenticated GitHub API operations without leaking tokens."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GitHub:
    def __init__(self, token: str | None) -> None:
        self.token = token

    def _request(self, path: str) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "OpenOcean-Release/1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(f"https://api.github.com{path}", headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API {path} failed ({error.code}): {detail}") from error

    def resolve_ref(self, repository: str, ref: str) -> str:
        value = self._request(f"/repos/{repository}/commits/{quote(ref, safe='')}")
        sha = value.get("sha") if isinstance(value, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RuntimeError(f"GitHub returned an invalid SHA for {repository}@{ref}")
        return sha

    def require_read_permission(self, repository: str, actor: str) -> None:
        from urllib.parse import quote
        value = self._request(f"/repos/{repository}/collaborators/{quote(actor, safe='')}/permission")
        if not isinstance(value, dict) or value.get("permission") not in {"read", "triage", "write", "maintain", "admin"}:
            raise RuntimeError(f"{actor} has no confirmed read permission for {repository}")

    def successful_workflow_run(self, repository: str, workflow: str, sha: str) -> str:
        from urllib.parse import quote
        response = self._request(
            f"/repos/{repository}/actions/workflows/{quote(workflow, safe='')}/runs"
            f"?head_sha={sha}&per_page=100")
        runs = response.get("workflow_runs") if isinstance(response, dict) else None
        if not isinstance(runs, list):
            raise RuntimeError(f"cannot read CI runs for {repository}/{workflow}@{sha}")
        matching = [run for run in runs if isinstance(run, dict) and run.get("head_sha") == sha]
        if not matching:
            raise RuntimeError(f"no CI run for {repository}/{workflow}@{sha}")
        latest = max(matching, key=lambda run: (str(run.get("created_at", "")), int(run.get("run_attempt") or 0), int(run.get("id") or 0)))
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise RuntimeError(f"CI is not successful for {repository}/{workflow}@{sha}: {latest.get('html_url', 'unknown run')}")
        url = latest.get("html_url")
        if not isinstance(url, str) or not url.startswith(f"https://github.com/{repository}/actions/runs/"):
            raise RuntimeError("CI returned an invalid run URL")
        return url

    def tags(self, repository: str) -> tuple[str, ...]:
        values = self._request(f"/repos/{repository}/tags?per_page=100")
        if not isinstance(values, list):
            raise RuntimeError("GitHub tags response is not a list")
        return tuple(item["name"] for item in values if isinstance(item, dict) and isinstance(item.get("name"), str))


def create_public_release(
    *, repository: str, tag: str, target_sha: str, title: str,
    notes_file: Path, assets: list[Path], token_env: str,
) -> None:
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"publishing requires {token_env}")
    environment = os.environ.copy()
    environment["GH_TOKEN"] = token
    existing = subprocess.run(
        ["gh", "api", f"repos/{repository}/git/ref/tags/{tag}"],
        env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if existing.returncode == 0:
        raise RuntimeError(f"refusing to overwrite existing tag {tag}")
    existing_release = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repository],
        env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if existing_release.returncode == 0:
        raise RuntimeError(f"refusing to overwrite existing GitHub Release {tag}")
    subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{repository}/git/refs",
         "-f", f"ref=refs/tags/{tag}", "-f", f"sha={target_sha}"],
        env=environment, check=True,
    )
    subprocess.run(
        ["gh", "release", "create", tag, *map(str, assets),
         "--repo", repository, "--title", title, "--notes-file", str(notes_file),
         "--verify-tag"],
        env=environment, check=True,
    )
