"""Replace only the published V1.0.0 Toolbox product and its hash metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import Request, urlopen

import yaml

from openocean_release.config import ReleaseConfig, RunnerConfig

REPOSITORY = "OpenOceanAcoustic/OpenOcean-Release"
TAG = "OpenOcean-Field-V1.0.0"
ASSET = "OpenOcean-Field-Toolbox-1.0.0-win64.zip"
METADATA = ("manifest.json", "SHA256SUMS", "release-lock.yaml")


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def get_json(url: str, token: str) -> dict:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "OpenOcean-Release/1",
    })
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def download(url: str, path: Path, token: str) -> None:
    request = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "OpenOcean-Release/1",
    })
    with urlopen(request, timeout=180) as response, path.open("wb") as output:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            output.write(block)


def checksum_entries(path: Path) -> dict[str, str]:
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        if not match or match[2] in entries:
            raise RuntimeError("published SHA256SUMS has an invalid or duplicate entry")
        entries[match[2]] = match[1]
    return entries


def prepare_metadata(
    directory: Path, new_asset: Path, old_lock: dict, new_lock: dict,
    toolbox_commit: str, build_run_id: str,
) -> None:
    if old_lock.get("releaseId") != "1.0.0" or new_lock.get("releaseId") != "1.0.0":
        raise RuntimeError("build and published locks must both target 1.0.0")
    old_sources = old_lock["sources"]
    new_sources = new_lock["sources"]
    if set(old_sources) != set(new_sources):
        raise RuntimeError("build source set differs from the published release")
    for name in old_sources:
        old_commit = old_sources[name]["commit"]
        new_commit = new_sources[name]["commit"]
        if name == "toolbox":
            if new_commit != toolbox_commit:
                raise RuntimeError("build did not use the configured Toolbox commit")
        elif new_commit != old_commit:
            raise RuntimeError(f"non-Toolbox source changed: {name}")

    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "openocean.release-manifest/v1" or manifest.get("releaseId") != "1.0.0":
        raise RuntimeError("published manifest identity is invalid")
    matches = [item for item in manifest["files"] if item["path"] == ASSET]
    if len(matches) != 1 or matches[0].get("type") != "matlab":
        raise RuntimeError("published manifest has no unique Toolbox asset")
    old_asset = directory / ASSET
    new_digest = digest(new_asset)
    current_digest = digest(old_asset)
    if current_digest not in {matches[0]["sha256"], new_digest}:
        raise RuntimeError("published Toolbox ZIP is neither the manifest asset nor the new build")
    if (current_digest == matches[0]["sha256"]
            and old_asset.stat().st_size != matches[0]["bytes"]):
        raise RuntimeError("published Toolbox ZIP size differs from its manifest")
    sums_path = directory / "SHA256SUMS"
    sums = checksum_entries(sums_path)
    if sums.get(ASSET) not in {matches[0]["sha256"], new_digest}:
        raise RuntimeError("published Toolbox checksum is unexpected")
    if (sums.get("manifest.json") != digest(manifest_path)
            and matches[0]["sha256"] != new_digest):
        raise RuntimeError("published manifest differs from SHA256SUMS")

    matches[0]["bytes"] = new_asset.stat().st_size
    matches[0]["sha256"] = new_digest
    matches[0]["sourceCommit"] = toolbox_commit
    matches[0]["validationRun"] = f"https://github.com/{REPOSITORY}/actions/runs/{build_run_id}"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sums[ASSET] = new_digest
    sums["manifest.json"] = digest(manifest_path)
    order = [line.split("  ", 1)[1] for line in sums_path.read_text(encoding="utf-8").splitlines()]
    sums_path.write_text("".join(f"{sums[name]}  {name}\n" for name in order), encoding="utf-8")
    if checksum_entries(sums_path)["manifest.json"] != digest(manifest_path):
        raise RuntimeError("new manifest checksum verification failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-run", required=True, help="GitHub run ID and attempt, such as 12345-1")
    parser.add_argument("--runner-config", type=Path, required=True)
    arguments = parser.parse_args()
    if not re.fullmatch(r"[0-9]+-[0-9]+", arguments.build_run):
        raise RuntimeError("--build-run must be RUN_ID-ATTEMPT")
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN is required")
    release = ReleaseConfig.load(Path("release.yaml"))
    if release.version != "1.0.0" or release.profile != "full":
        raise RuntimeError("checked-in release must be the 1.0.0 full profile")
    toolbox_commit = release.sources["toolbox"].ref
    if not re.fullmatch(r"[0-9a-f]{40}", toolbox_commit):
        raise RuntimeError("Toolbox ref must be a pinned 40-character commit")
    runner = RunnerConfig.load(arguments.runner_config)
    build_dir = runner.storage("releases") / "toolbox-refresh" / arguments.build_run / "1.0.0"
    state = json.loads((build_dir / "state.json").read_text(encoding="utf-8"))
    summary = json.loads((build_dir / "test-summary.json").read_text(encoding="utf-8"))
    if state.get("sealed") is not True or summary.get("status") != "passed" or summary.get("failed"):
        raise RuntimeError("isolated Toolbox build is not sealed with all tests passed")
    new_lock = yaml.safe_load((build_dir / "release-lock.yaml").read_text(encoding="utf-8"))
    if new_lock.get("profile") != "matlab":
        raise RuntimeError("isolated build must use the MATLAB profile")
    new_asset = build_dir / "assets" / ASSET
    built_manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    built_files = built_manifest.get("files", [])
    if len(built_files) != 1 or built_files[0].get("path") != ASSET:
        raise RuntimeError("isolated build produced unexpected product assets")
    if digest(new_asset) != built_files[0]["sha256"]:
        raise RuntimeError("isolated Toolbox ZIP differs from its sealed manifest")

    api_url = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{TAG}"
    published = get_json(api_url, token)
    if published.get("tag_name") != TAG or published.get("draft"):
        raise RuntimeError("the expected public 1.0.0 Release was not found")
    assets = {item["name"]: item for item in published["assets"]}
    if not set((ASSET, *METADATA)).issubset(assets):
        raise RuntimeError("the expected published assets were not found")
    with tempfile.TemporaryDirectory(prefix="toolbox-refresh-") as temporary:
        workspace = Path(temporary)
        for name in (ASSET, *METADATA):
            download(assets[name]["browser_download_url"], workspace / name, token)
        old_lock = yaml.safe_load((workspace / "release-lock.yaml").read_text(encoding="utf-8"))
        prepare_metadata(
            workspace, new_asset, old_lock, new_lock, toolbox_commit,
            arguments.build_run.split("-", 1)[0],
        )
        # The original lock, configuration, and full-release test summary remain
        # historical records. The refreshed Toolbox entry names its own source
        # commit and validation run. No other product archive is uploaded.
        for path in (new_asset, workspace / "manifest.json", workspace / "SHA256SUMS"):
            subprocess.run([
                "gh", "release", "upload", TAG, str(path), "--clobber",
                "--repo", REPOSITORY,
            ], check=True)
        current = get_json(api_url, token)
        current_assets = {item["name"]: item for item in current["assets"]}
        for name, path in ((ASSET, new_asset),
                           ("manifest.json", workspace / "manifest.json"),
                           ("SHA256SUMS", workspace / "SHA256SUMS")):
            remote = current_assets.get(name)
            if remote is None or remote["size"] != path.stat().st_size:
                raise RuntimeError(f"uploaded {name} is missing or has the wrong size")
            remote_digest = remote.get("digest")
            if remote_digest:
                if remote_digest != f"sha256:{digest(path)}":
                    raise RuntimeError(f"uploaded {name} has the wrong SHA256")
            else:
                verification = workspace / f"verify-{name}"
                download(remote["browser_download_url"] + "?verify=1", verification, token)
                if digest(verification) != digest(path):
                    raise RuntimeError(f"uploaded {name} has the wrong SHA256")
        print(f"Updated {TAG}/{ASSET}: sha256:{digest(new_asset)}")
        print("Updated manifest.json and SHA256SUMS; other product assets were not uploaded")


if __name__ == "__main__":
    main()
