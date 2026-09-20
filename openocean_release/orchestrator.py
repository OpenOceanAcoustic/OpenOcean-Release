"""Release resolution, execution, sealing, resume, and publication."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable, Iterable, Mapping, Sequence

import yaml

from .config import BACKENDS, LOCK_SCHEMA, ReleaseConfig, RunnerConfig
from .github import GitHub, create_public_release
from .runtime import EventLogger, TaskState, sha256_file, stable_digest


RELEASE_REPOSITORY = "OpenOceanAcoustic/OpenOcean-Release"
SOURCE_DIRECTORIES = {
    "field_core": "OpenOcean-Field-Core",
    "ray_mode": "OpenOcean-Field-RayMode",
    "normal_mode": "OpenOcean-Field-NormalMode",
    "pe": "OpenOcean-Field-PE",
    "toolbox": "OpenOcean-Field-Toolbox",
}
NATIVE_ASSET_NAMES = {
    "field_core": "OpenOcean-Field-Core",
    "ray_mode": "OpenOcean-Field-RayMode",
    "normal_mode": "OpenOcean-Field-NormalMode",
    "pe": "OpenOcean-Field-PE",
}


def _output(command: Sequence[str], cwd: Path | None = None) -> str:
    return subprocess.check_output(list(command), cwd=cwd, text=True).strip()


def _tool_version(command: Sequence[str]) -> str:
    try:
        return _output(command).splitlines()[0]
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _ps(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _copy_source(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".git", "build", "dist", "__pycache__", "*.pyc"),
    )


def _version_key(value: str) -> tuple[int, int, int, int] | None:
    if not re.fullmatch(r"[1-9][0-9]*\.[0-9]+\.[0-9]+\.[1-9][0-9]*", value):
        return None
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


class Orchestrator:
    def __init__(
        self,
        release: ReleaseConfig,
        runner: RunnerConfig,
        *,
        resume: str | None = None,
        rebuild: Iterable[str] = (),
    ) -> None:
        self.release = release
        self.runner = runner
        self.resume = resume
        self.rebuild = set(rebuild)
        source_env = runner.credential_env("source_read_token_env")
        publish_env = runner.credential_env("github_publish_token_env")
        self.source_token_env = source_env
        self.publish_token_env = publish_env
        self.source_token = os.environ.get(source_env, "")
        self.github = GitHub(self.source_token or os.environ.get(publish_env))
        self.release_id = ""
        self.release_dir = Path()
        self.assets_dir = Path()
        self.logs_dir = Path()
        self.state: TaskState | None = None
        self.logger: EventLogger | None = None
        self.resolved_sources: dict[str, str] = {}
        self.source_paths: dict[str, Path] = {}
        self.orchestrator_sha = _output(
            ["git", "-c", f"safe.directory={release.path.parent}",
             "rev-parse", "HEAD"],
            release.path.parent,
        )
        self.vm_was_running: bool | None = None

    def _select_version(self) -> str:
        if self.resume:
            return self.resume
        if self.release.version != "auto":
            return self.release.version
        now = dt.datetime.now().astimezone()
        prefix = f"{now.year}.{now.month}.{now.day}."
        candidates: list[int] = []
        for tag in self.github.tags(RELEASE_REPOSITORY):
            match = re.fullmatch(rf"v{re.escape(prefix)}([1-9][0-9]*)", tag)
            if match:
                candidates.append(int(match.group(1)))
        releases_root = self.runner.storage("releases")
        if releases_root.is_dir():
            for entry in releases_root.iterdir():
                match = re.fullmatch(rf"{re.escape(prefix)}([1-9][0-9]*)", entry.name)
                if match:
                    candidates.append(int(match.group(1)))
        return prefix + str(max(candidates, default=0) + 1)

    def prepare(self) -> None:
        self.release_id = self._select_version()
        self.release_dir = self.runner.storage("releases") / self.release_id
        self.assets_dir = self.release_dir / "assets"
        self.logs_dir = self.release_dir / "logs"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        secret_values = [
            os.environ.get(self.source_token_env, ""),
            os.environ.get(self.publish_token_env, ""),
        ]
        logging = self.runner.document.get("logging", {})
        if isinstance(logging, Mapping):
            names = logging.get("redact_environment", ())
            if isinstance(names, list):
                secret_values.extend(
                    os.environ.get(name, "") for name in names
                    if isinstance(name, str))
        self.logger = EventLogger(self.logs_dir, secret_values)
        self.state = TaskState.open(self.release_dir / "state.json", self.release_id)
        if self.state.document.get("sealed") is True:
            raise RuntimeError(
                f"release {self.release_id} is already sealed; publish it or choose a new version")
        self.logger.event("release", "INFO", f"release ID: {self.release_id}")

    def preflight(self, *, publishing: bool = False) -> None:
        logger = self.logger or EventLogger(Path(tempfile.mkdtemp(prefix="openocean-preflight-")))
        errors: list[str] = []
        try:
            dirty = _output(
                ["git", "-c", f"safe.directory={self.release.path.parent}",
                 "status", "--porcelain", "--untracked-files=all"],
                self.release.path.parent,
            )
            if dirty:
                errors.append(
                    "OpenOcean-Release has uncommitted files; commit them so "
                    "the orchestrator SHA describes the code being executed")
        except (OSError, subprocess.CalledProcessError):
            errors.append("OpenOcean-Release configuration is not inside a Git worktree")
        for executable in ("git", "cmake", "docker", "gh"):
            if shutil.which(executable) is None:
                errors.append(f"missing executable: {executable}")
        if not self.source_token:
            errors.append(f"missing private source credential: {self.source_token_env}")
        if publishing and not os.environ.get(self.publish_token_env):
            errors.append(f"missing publish credential: {self.publish_token_env}")
        for name in ("root", "linux", "windows", "cache", "staging", "releases"):
            try:
                path = self.runner.storage(name)
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".openocean-write-probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
            except OSError as error:
                errors.append(f"runner.storage.{name} is not writable: {error}")
        if (self.release.products.native or self.release.products.python) and shutil.which("docker") is not None:
            linux = self.runner.section("linux")
            image = linux.get("image")
            if not isinstance(image, str) or not image:
                errors.append("runner.linux.image is required")
            elif subprocess.run(
                ["docker", "image", "inspect", image],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode:
                errors.append(
                    f"missing pinned Linux Docker image: {image}; build it with "
                    "tools/build_linux_release_image.sh and update runner.linux.image")
            elif self.release.products.python:
                probe = (
                    "command -v cmake >/dev/null && command -v ninja >/dev/null"
                    " && " + " && ".join(
                        f"test -x /opt/python/{abi}-{abi}/bin/python"
                        for abi in self.release.python_versions))
                if subprocess.run(
                    ["docker", "run", "--rm", "--pull=never", image,
                     "bash", "-lc", probe],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                ).returncode:
                    errors.append(
                        "pinned Linux image lacks CMake, Ninja, or the CPython "
                        "3.10-3.14 /opt/python matrix")
        if self.release.products.matlab or "windows-x86_64" in (
            self.release.native_platforms + self.release.python_platforms
        ):
            windows = self.runner.section("windows")
            windows_ready = True
            for key in ("vm_controller", "powershell_runner"):
                value = windows.get(key)
                if not isinstance(value, str) or not Path(value).is_file():
                    errors.append(f"runner.windows.{key} is unavailable: {value}")
                    windows_ready = False
            for key in (
                "shared_host_root", "shared_guest_root", "ssh_host", "ssh_user",
                "build_python", "wheelhouse", "cibuildwheel_cache",
            ):
                if not isinstance(windows.get(key), str) or not windows[key]:
                    errors.append(f"runner.windows.{key} is required")
                    windows_ready = False
            if self.release.products.matlab and (
                    not isinstance(windows.get("matlab"), str)
                    or not windows["matlab"]):
                errors.append("runner.windows.matlab is required")
                windows_ready = False
            for key in ("ssh_private_key", "ssh_known_hosts"):
                value = windows.get(key)
                if not isinstance(value, str) or not Path(value).is_file():
                    errors.append(f"runner.windows.{key} is unavailable: {value}")
                    windows_ready = False
            if not isinstance(windows.get("ssh_port"), int):
                errors.append("runner.windows.ssh_port must be an integer")
                windows_ready = False
            if windows_ready:
                was_logger = self.logger
                self.logger = logger
                checks = [
                    "$ErrorActionPreference = 'Stop'",
                    "$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'",
                    "if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Install Visual Studio 2022 Build Tools with the C++ workload.' }",
                    "$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath",
                    "if (-not $vs) { throw 'Install the Visual Studio 2022 x64 C++ workload.' }",
                    f"New-Item -ItemType Directory -Force -Path {_ps(str(windows['shared_guest_root']))} | Out-Null",
                    f"if (-not (Test-Path -LiteralPath {_ps(str(windows['build_python']))})) {{ throw 'Restore the isolated Windows release Python at runner.windows.build_python.' }}",
                ]
                if self.release.products.python:
                    try:
                        self._ensure_windows_python_cache(windows)
                    except (OSError, subprocess.CalledProcessError) as error:
                        errors.append(
                            "Windows CPython/wheelhouse auto-provision failed: "
                            f"{error}")
                    checks += [
                        f"if (-not (Test-Path -LiteralPath (Join-Path {_ps(str(windows['wheelhouse']))} 'openocean-v2.complete'))) {{ throw 'Automatic Windows wheelhouse provisioning did not complete.' }}",
                        f"$cbw = & {_ps(str(windows['build_python']))} -c \"import importlib.metadata as m; print(m.version('cibuildwheel'))\"",
                        "if ($cbw -ne '3.4.0') { throw 'Install cibuildwheel==3.4.0 in the configured Windows build Python environment.' }",
                    ]
                if self.release.products.matlab:
                    checks += [
                        "$installationType = (Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion').InstallationType",
                        "if ($installationType -eq 'Server Core') { throw 'MATLAB toolbox validation requires Windows Server with Desktop Experience. Server Core cannot load the graphics runtime; create a new Desktop Experience VM and restore the release toolchain.' }",
                        f"$matlab = {_ps(str(windows['matlab']))}",
                        "if (-not (Test-Path -LiteralPath $matlab)) { throw 'Install MATLAB R2025a at the configured runner.windows.matlab path.' }",
                        "& $matlab -batch \"actual=string(version('-release')); assert(actual=='2025a','OpenOcean:WrongMATLABRelease','Expected MATLAB R2025a, found %s.',actual);\"",
                        "if ($LASTEXITCODE -ne 0) { throw 'The configured MATLAB executable is not R2025a.' }",
                        "& $matlab -batch \"f=figure('Visible','off'); imagesc([1 2;3 4]); drawnow; close(f); disp('OPENOCEAN_MATLAB_GRAPHICS_OK');\"",
                        "if ($LASTEXITCODE -ne 0) { throw 'MATLAB graphics smoke test failed. Repair the Desktop Experience VM and MATLAB installation before publishing.' }",
                    ]
                try:
                    self._run_powershell("preflight.windows", "\n".join(checks) + "\n")
                except (OSError, subprocess.CalledProcessError) as error:
                    errors.append(f"Windows runner preflight failed: {error}")
                finally:
                    try:
                        self._restore_vm()
                    finally:
                        self.logger = was_logger
        for error in errors:
            logger.event("preflight", "ERROR", error)
        if errors:
            raise RuntimeError("release preflight failed; see diagnostics above")
        logger.event("preflight", "INFO", "host release prerequisites passed")

    def _run_task(
        self,
        name: str,
        inputs: object,
        outputs: Sequence[Path],
        action: Callable[[], None],
    ) -> None:
        assert self.state is not None and self.logger is not None
        input_hash = stable_digest(inputs)
        if name not in self.rebuild and self.state.reusable(name, input_hash, outputs):
            self.logger.event(name, "INFO", "reusing checksum-verified task output")
            return
        self.state.start(name, input_hash)
        self.logger.event(name, "INFO", "started")
        try:
            action()
            missing = [str(path) for path in outputs if not path.is_file()]
            if missing:
                raise RuntimeError(f"task did not create expected outputs: {', '.join(missing)}")
            self.state.succeed(name, outputs)
            self.logger.event(name, "INFO", "succeeded")
        except BaseException as error:
            self.state.fail(name, error)
            self.logger.event(name, "ERROR", str(error))
            raise

    def resolve_sources(self) -> None:
        assert self.logger is not None
        lock_path = self.release_dir / "resolved-sources.json"

        def action() -> None:
            self.resolved_sources = {}
            for name, source in self.release.sources.items():
                if not source.enabled:
                    continue
                self.logger.event("resolve", "INFO", f"resolving {source.repository}@{source.ref}")
                self.resolved_sources[name] = self.github.resolve_ref(source.repository, source.ref)
            lock_path.write_text(json.dumps(self.resolved_sources, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self._run_task(
            "resolve", {name: vars(source) for name, source in self.release.sources.items()},
            [lock_path], action,
        )
        self.resolved_sources = json.loads(lock_path.read_text(encoding="utf-8"))

    def _checkout_one(self, name: str) -> Path:
        assert self.logger is not None
        source = self.release.sources[name]
        sha = self.resolved_sources[name]
        root = self.runner.storage("staging") / self.release_id / "sources"
        destination = root / SOURCE_DIRECTORIES[name]
        marker = destination / ".openocean-release-source.json"

        def action() -> None:
            if destination.exists():
                shutil.rmtree(destination)
            destination.mkdir(parents=True)
            askpass = root / ".git-askpass.sh"
            askpass.write_text(
                "#!/bin/sh\ncase \"$1\" in *Username*) echo x-access-token;; *) printf '%s\\n' \"$OOA_GIT_TOKEN\";; esac\n",
                encoding="utf-8",
            )
            askpass.chmod(askpass.stat().st_mode | stat.S_IXUSR)
            environment = os.environ.copy()
            environment.update({
                "GIT_ASKPASS": str(askpass),
                "GIT_TERMINAL_PROMPT": "0",
                "OOA_GIT_TOKEN": self.source_token,
            })
            try:
                self.logger.command(f"checkout.{name}", ["git", "init"], cwd=destination, env=environment)
                self.logger.command(
                    f"checkout.{name}",
                    ["git", "remote", "add", "origin", f"https://github.com/{source.repository}.git"],
                    cwd=destination, env=environment,
                )
                self.logger.command(
                    f"checkout.{name}", ["git", "fetch", "--depth", "1", "origin", sha],
                    cwd=destination, env=environment,
                )
                self.logger.command(
                    f"checkout.{name}", ["git", "checkout", "--detach", "FETCH_HEAD"],
                    cwd=destination, env=environment,
                )
                marker.write_text(json.dumps({"repository": source.repository, "sha": sha}) + "\n", encoding="utf-8")
            finally:
                askpass.unlink(missing_ok=True)

        self._run_task(f"checkout.{name}", {"repository": source.repository, "sha": sha}, [marker], action)
        self.source_paths[name] = destination
        return destination

    def checkout_sources(self) -> None:
        for name in self.resolved_sources:
            self._checkout_one(name)

    def _linux_native(self, family: str) -> Path:
        assert self.logger is not None
        source = self.source_paths[family]
        output = self.runner.storage("linux") / self.release_id / "native" / family
        build = self.runner.storage("linux") / self.release_id / "build" / family
        extension = "tar.gz"
        asset = self.assets_dir / f"{NATIVE_ASSET_NAMES[family]}-{self.release_id}-linux-x86_64.{extension}"

        def action() -> None:
            if output.exists():
                shutil.rmtree(output)
            output.mkdir(parents=True)
            environment = os.environ.copy()
            environment.update({
                "OOA_LINUX_DIST_IMAGE": str(self.runner.section("linux")["image"]),
                "OOA_LINUX_DIST_DIR": str(output),
                "OOA_LINUX_BUILD_DIR": str(build),
                "OOA_FIELD_CI_CACHE_DIR": str(self.runner.storage("cache")),
                "GITHUB_RUN_ID": self.release_id.replace(".", ""),
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_SHA": self.resolved_sources[family],
            })
            self.logger.command(
                f"linux.native.{family}", ["bash", "tools/linux_dist.sh", "--no-wheel"],
                cwd=source, env=environment,
            )
            archives = list(output.glob("*.tar.gz"))
            if len(archives) != 1:
                raise RuntimeError(f"expected one Linux native archive for {family}, found {len(archives)}")
            shutil.copy2(archives[0], asset)

        self._run_task(
            f"linux.native.{family}",
            {"sha": self.resolved_sources[family], "config": self.release.sha256(), "image": self.runner.section("linux")["image"]},
            [asset], action,
        )
        return asset

    def _vm_paths(self) -> tuple[Path, str]:
        windows = self.runner.section("windows")
        return Path(str(windows["shared_host_root"])).resolve(), str(windows["shared_guest_root"]).rstrip("\\/")

    def _scp_command(self) -> list[str]:
        windows = self.runner.section("windows")
        return [
            "scp", "-q", "-P", str(windows["ssh_port"]),
            "-i", str(windows["ssh_private_key"]),
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={windows['ssh_known_hosts']}",
        ]

    def _guest_spec(self, path: str) -> str:
        windows = self.runner.section("windows")
        normalized = path.replace("\\", "/")
        return f"{windows['ssh_user']}@{windows['ssh_host']}:{normalized}"

    def _copy_to_guest(self, task: str, source: Path, destination: str) -> None:
        assert self.logger is not None
        command = self._scp_command()
        if source.is_dir():
            command.append("-r")
        command += [str(source), self._guest_spec(destination)]
        self.logger.command(task, command)

    def _copy_from_guest(self, task: str, source: str, destination: Path) -> None:
        assert self.logger is not None
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.logger.command(
            task, self._scp_command() + [self._guest_spec(source), str(destination)])

    def _ensure_vm(self) -> None:
        if self.vm_was_running is not None:
            return
        windows = self.runner.section("windows")
        controller = str(windows["vm_controller"])
        status = subprocess.run(
            [sys.executable, controller, "status"], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        text = status.stdout.lower()
        self.vm_was_running = "running" in text and "not running" not in text
        if not self.vm_was_running:
            assert self.logger is not None
            self.logger.command("windows.vm", [sys.executable, controller, "start"])

    def _restore_vm(self) -> None:
        if self.vm_was_running is False and self.runner.section("windows").get("restore_previous_vm_state", True):
            assert self.logger is not None
            self.logger.command(
                "windows.vm", [sys.executable, str(self.runner.section("windows")["vm_controller"]), "stop"]
            )
        self.vm_was_running = None

    def _run_powershell(self, task: str, script: str) -> None:
        self._ensure_vm()
        assert self.logger is not None
        runner = str(self.runner.section("windows")["powershell_runner"])
        self.logger.command(task, [runner], input_text=script)

    def _ensure_windows_python_cache(self, windows: Mapping[str, object]) -> None:
        """Restore the pinned cibuildwheel interpreters and wheelhouse on demand."""
        provisioner = self.release.path.parent / "tools" / "provision_windows_wheelhouse.ps1"
        if not provisioner.is_file():
            raise RuntimeError(
                f"Windows wheelhouse provisioner is missing: {provisioner}")
        _, guest_root = self._vm_paths()
        guest_tools = guest_root + "\\runner-tools"
        guest_provisioner = guest_tools + "\\provision_windows_wheelhouse.ps1"
        self._run_powershell(
            "preflight.windows.cache",
            f"New-Item -ItemType Directory -Force -Path {_ps(guest_tools)} | Out-Null\n",
        )
        self._copy_to_guest(
            "preflight.windows.cache", provisioner, guest_provisioner)
        wheelhouse = str(windows["wheelhouse"])
        build_python = str(windows["build_python"])
        cibuildwheel_cache = str(windows["cibuildwheel_cache"])
        script = f"""
$ErrorActionPreference = 'Stop'
$marker = Join-Path {_ps(wheelhouse)} 'openocean-v2.complete'
if (-not (Test-Path -LiteralPath $marker)) {{
  & {_ps(guest_provisioner)} -ToolPython {_ps(build_python)} `
    -Wheelhouse {_ps(wheelhouse)} `
    -CibuildwheelCache {_ps(cibuildwheel_cache)} -KeepProxy
  if ($LASTEXITCODE -ne 0) {{ throw 'Windows wheelhouse provisioner failed' }}
}}
"""
        self._run_powershell("preflight.windows.cache", script)

    def _stage_windows_sources(self) -> tuple[Path, str]:
        host_root, guest_root = self._vm_paths()
        host_sources = host_root / self.release_id / "sources"
        guest_sources = f"{guest_root}\\{self.release_id}\\sources"
        marker = host_sources / ".complete.json"

        def action() -> None:
            if host_sources.exists():
                shutil.rmtree(host_sources)
            host_sources.mkdir(parents=True)
            for name, source in self.source_paths.items():
                _copy_source(source, host_sources / SOURCE_DIRECTORIES[name])
            marker.write_text(json.dumps(self.resolved_sources, sort_keys=True) + "\n", encoding="utf-8")
            self._run_powershell(
                "windows.stage-sources",
                f"$root = {_ps(guest_sources)}\n"
                "if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }\n"
                "New-Item -ItemType Directory -Force -Path $root | Out-Null\n",
            )
            for name in self.source_paths:
                self._copy_to_guest(
                    "windows.stage-sources",
                    host_sources / SOURCE_DIRECTORIES[name],
                    guest_sources,
                )
            self._copy_to_guest(
                "windows.stage-sources", marker, guest_sources + "\\.complete.json")

        self._run_task("windows.stage-sources", self.resolved_sources, [marker], action)
        # The state file can outlive a reverted VM snapshot.  Verify the guest
        # marker even when the host-side task was resumed, then restage if the
        # VM no longer contains the matching source set.
        expected = json.dumps(self.resolved_sources, sort_keys=True)
        guest_marker = guest_sources + "\\.complete.json"
        probe = (
            f"$marker = {_ps(guest_marker)}\n"
            "if (-not (Test-Path -LiteralPath $marker)) { exit 42 }\n"
            "$actual = (Get-Content -LiteralPath $marker -Raw).Trim()\n"
            f"if ($actual -ne {_ps(expected)}) {{ exit 43 }}\n"
        )
        try:
            self._run_powershell("windows.stage-sources.verify", probe)
        except subprocess.CalledProcessError:
            self.logger.event(
                "windows.stage-sources", "WARNING",
                "guest source checkpoint is absent or stale; restaging sources",
            )
            self.rebuild.add("windows.stage-sources")
            self._run_task(
                "windows.stage-sources", self.resolved_sources, [marker], action)
            self._run_powershell("windows.stage-sources.verify", probe)
        return host_sources, guest_sources

    def _windows_native(self, family: str, guest_sources: str) -> Path:
        host_root, guest_root = self._vm_paths()
        source = f"{guest_sources}\\{SOURCE_DIRECTORIES[family]}"
        host_output = host_root / self.release_id / "native" / family
        host_output.mkdir(parents=True, exist_ok=True)
        guest_output = f"{guest_root}\\{self.release_id}\\native\\{family}"
        asset = self.assets_dir / f"{NATIVE_ASSET_NAMES[family]}-{self.release_id}-windows-x86_64.zip"
        guest_asset = f"{guest_output}\\{asset.name}"
        python = str(self.runner.section("windows")["build_python"])
        script = f"""
$ErrorActionPreference = 'Stop'
$source = {_ps(source)}
$env:GITHUB_SHA = {_ps(self.resolved_sources[family])}
$build = Join-Path {_ps(guest_root)} {_ps(self.release_id + '\\build\\native\\' + family)}
$output = {_ps(guest_output)}
$cmake = (Get-Command cmake.exe -ErrorAction SilentlyContinue).Source
if (-not $cmake) {{
  $vswhere = Join-Path ${{env:ProgramFiles(x86)}} 'Microsoft Visual Studio/Installer/vswhere.exe'
  if (-not (Test-Path $vswhere)) {{ throw 'Visual Studio 2022 C++ workload is required' }}
  $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
  $cmake = Join-Path $vs 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'
}}
if (-not (Test-Path $cmake)) {{ throw "CMake is missing: $cmake" }}
if (Test-Path $build) {{ Remove-Item -Recurse -Force $build }}
New-Item -ItemType Directory -Force -Path $output | Out-Null
& $cmake -S $source -B $build -G 'Visual Studio 17 2022' -A x64 `
  -DOPENOCEAN_FIELD_BUILD_DIST=ON -DOPENOCEAN_FIELD_DIST_WHEEL=OFF `
  -DOPENOCEAN_FIELD_DIST_WASM=OFF -DPython3_EXECUTABLE={_ps(python)}
if ($LASTEXITCODE -ne 0) {{ throw 'CMake configure failed' }}
& $cmake --build $build --target dist --config Release --parallel 1
if ($LASTEXITCODE -ne 0) {{ throw 'CMake dist failed' }}
Compress-Archive -Path (Join-Path $build 'dist\\*') -DestinationPath {_ps(guest_asset)} -Force
"""

        def action() -> None:
            self._run_powershell(f"windows.native.{family}", script)
            self._copy_from_guest(
                f"windows.native.{family}", guest_asset, host_output / asset.name)
            shutil.copy2(host_output / asset.name, asset)

        self._run_task(
            f"windows.native.{family}",
            {"sha": self.resolved_sources[family], "config": self.release.sha256(), "msvc": "Visual Studio 17 2022"},
            [asset], action,
        )
        return asset

    def _toolbox_script(self, name: str) -> Path:
        path = self.source_paths["toolbox"] / "scripts" / name
        if not path.is_file():
            raise RuntimeError(f"Toolbox release adapter is missing: {path.name}")
        return path

    def _linux_python(self) -> Path:
        assert self.logger is not None
        output = self.runner.storage("linux") / self.release_id / "python"
        asset = self.assets_dir / f"OpenOcean-Field-Python-{self.release_id}-linux-x86_64.tar.gz"
        script = self._toolbox_script("build_python_sdk.py")
        image = str(self.runner.section("linux")["image"])
        cache = self.runner.storage("cache") / "python"

        def action() -> None:
            output.mkdir(parents=True, exist_ok=True)
            cache.mkdir(parents=True, exist_ok=True)
            container_sources = {
                name: f"/sources/{SOURCE_DIRECTORIES[name]}"
                for name in ("field_core", "ray_mode", "normal_mode", "pe", "toolbox")
            }
            command = [
                "docker", "run", "--rm", "--pull=never", "--init",
                "--network", "host",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--env", "HOME=/tmp/openocean-release-home",
                "--env", "OPENOCEAN_PYTHON_BUILD_CACHE=/cache",
                "--env", "PIP_CACHE_DIR=/cache/pip",
                "--env", "PIP_DISABLE_PIP_VERSION_CHECK=1",
                "--env", f"OPENOCEAN_NATIVE_TOOLCHAIN_ID={image}",
                "--env", f"CMAKE_BUILD_PARALLEL_LEVEL={os.environ.get('CMAKE_BUILD_PARALLEL_LEVEL', '2')}",
                "--volume", f"{output}:/output",
                "--volume", f"{cache}:/cache",
            ]
            for name, source in self.source_paths.items():
                if name in container_sources:
                    command += ["--volume", f"{source}:{container_sources[name]}:ro"]
            for variable in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
                if self.runner.section("linux").get("inherit_proxy", True) and os.environ.get(variable):
                    command += ["--env", variable]
            command += [
                image, "/opt/python/cp314-cp314/bin/python",
                container_sources["toolbox"] + "/scripts/build_python_sdk.py",
                "--platform", "linux", "--version", self.release_id,
                "--output", "/output",
            ]
            for name in ("field_core", "ray_mode", "normal_mode", "pe", "toolbox"):
                command += [f"--source-{name.replace('_', '-')}", container_sources[name]]
            self.logger.command("linux.python", command)
            built = output / asset.name
            if not built.is_file():
                raise RuntimeError(f"Python SDK adapter did not create {built}")
            shutil.copy2(built, asset)

        self._run_task(
            "linux.python", {"sources": self.resolved_sources, "versions": self.release.python_versions, "adapter": sha256_file(script), "image": image},
            [asset], action,
        )
        return asset

    def _windows_python(self, guest_sources: str) -> Path:
        host_root, guest_root = self._vm_paths()
        host_output = host_root / self.release_id / "python"
        host_output.mkdir(parents=True, exist_ok=True)
        guest_output = f"{guest_root}\\{self.release_id}\\python"
        asset = self.assets_dir / f"OpenOcean-Field-Python-{self.release_id}-windows-x86_64.zip"
        adapter = f"{guest_sources}\\{SOURCE_DIRECTORIES['toolbox']}\\scripts\\build_python_sdk.py"
        python = str(self.runner.section("windows")["build_python"])
        wheelhouse = str(self.runner.section("windows")["wheelhouse"])
        cibuildwheel_cache = str(
            self.runner.section("windows")["cibuildwheel_cache"])
        guest_cache = guest_root + "\\cache\\python"
        guest_pip_cache = guest_cache + "\\pip"
        arguments = [
            f"& {_ps(python)} {_ps(adapter)} --platform windows --version {_ps(self.release_id)} --output {_ps(guest_output)}",
        ]
        for name in ("field_core", "ray_mode", "normal_mode", "pe", "toolbox"):
            guest_source = guest_sources + "\\" + SOURCE_DIRECTORIES[name]
            arguments.append(
                f" --source-{name.replace('_', '-')} {_ps(guest_source)}"
            )
        arguments.append(f" --wheelhouse {_ps(wheelhouse)}")
        script = (
            "$ErrorActionPreference = 'Stop'\n"
            "$env:OPENOCEAN_NATIVE_TOOLCHAIN_ID = 'Visual Studio 17 2022 x64'\n"
            f"$env:CIBW_CACHE_PATH = {_ps(cibuildwheel_cache)}\n"
            f"$env:OPENOCEAN_PYTHON_BUILD_CACHE = {_ps(guest_cache)}\n"
            f"$env:PIP_CACHE_DIR = {_ps(guest_pip_cache)}\n"
            + "".join(arguments)
            + "\nif ($LASTEXITCODE -ne 0) { throw 'Python SDK build failed' }\n"
        )

        def action() -> None:
            self._run_powershell("windows.python", script)
            built = host_output / asset.name
            self._copy_from_guest(
                "windows.python", f"{guest_output}\\{asset.name}", built)
            shutil.copy2(built, asset)

        self._run_task(
            "windows.python", {"sources": self.resolved_sources, "versions": self.release.python_versions, "python": python},
            [asset], action,
        )
        return asset

    def _windows_matlab(self, guest_sources: str) -> Path:
        host_root, guest_root = self._vm_paths()
        host_output = host_root / self.release_id / "matlab"
        host_output.mkdir(parents=True, exist_ok=True)
        guest_output = f"{guest_root}\\{self.release_id}\\matlab"
        asset = self.assets_dir / f"OpenOcean-Field-Toolbox-{self.release_id}-win64.mltbx"
        adapter = f"{guest_sources}\\{SOURCE_DIRECTORIES['toolbox']}\\scripts\\build_matlab_release.ps1"
        matlab = str(self.runner.section("windows")["matlab"])
        build_python = str(self.runner.section("windows")["build_python"])
        script = f"""
$ErrorActionPreference = 'Stop'
& {_ps(adapter)} -SourcesRoot {_ps(guest_sources)} -OutputDirectory {_ps(guest_output)} `
  -Version {_ps(self.release_id)} -MatlabExecutable {_ps(matlab)} `
  -BuildPython {_ps(build_python)} -TestRelease 'R2025a'
if ($LASTEXITCODE -ne 0) {{ throw 'MATLAB release adapter failed' }}
"""

        def action() -> None:
            self._run_powershell("windows.matlab", script)
            built = host_output / asset.name
            self._copy_from_guest(
                "windows.matlab", f"{guest_output}\\{asset.name}", built)
            shutil.copy2(built, asset)

        self._run_task(
            "windows.matlab", {"sources": self.resolved_sources, "version": self.release_id, "matlab": "R2025a"},
            [asset], action,
        )
        return asset

    def _seal(self) -> None:
        assert self.state is not None
        config_path = self.release_dir / "release-config.yaml"
        lock_path = self.release_dir / "release-lock.yaml"
        manifest_path = self.release_dir / "manifest.json"
        checksums_path = self.release_dir / "SHA256SUMS"
        summary_path = self.release_dir / "test-summary.json"
        notes_path = self.release_dir / "release-notes.md"
        document = json.loads(json.dumps(self.release.document))
        document["release"]["version"] = self.release_id
        config_bytes = yaml.safe_dump(document, sort_keys=True, allow_unicode=True).encode("utf-8")
        config_path.write_bytes(config_bytes)
        toolchains = {
            "host": platform.platform(),
            "orchestratorPython": platform.python_version(),
            "hostCMake": _tool_version(["cmake", "--version"]),
            "hostCompiler": _tool_version(["c++", "--version"]),
            "docker": _tool_version(["docker", "--version"]),
            "linuxImage": self.runner.section("linux")["image"],
            "windowsCompiler": (
                "Visual Studio 17 2022 x64"
                if "windows-x86_64" in (
                    self.release.native_platforms + self.release.python_platforms
                ) or self.release.products.matlab else None
            ),
            "cibuildwheel": "3.4.0",
            "matlabTested": "R2025a" if self.release.products.matlab else None,
        }
        lock = {
            "schema": LOCK_SCHEMA,
            "releaseId": self.release_id,
            "profile": self.release.profile,
            "orchestrator": {"repository": RELEASE_REPOSITORY, "commit": self.orchestrator_sha},
            "sources": {
                name: {
                    "repository": self.release.sources[name].repository,
                    "requestedRef": self.release.sources[name].ref,
                    "commit": sha,
                }
                for name, sha in self.resolved_sources.items()
            },
            "matrix": {
                "nativePlatforms": list(self.release.native_platforms) if self.release.products.native else [],
                "pythonPlatforms": list(self.release.python_platforms) if self.release.products.python else [],
                "pythonVersions": list(self.release.python_versions) if self.release.products.python else [],
                "matlabPlatform": "windows-x86_64" if self.release.products.matlab else None,
                "fieldRunnerBackends": list(BACKENDS) if self.release.products.field_runner else [],
            },
            "toolchains": toolchains,
            "configSha256": __import__("hashlib").sha256(config_bytes).hexdigest(),
        }
        lock_path.write_text(yaml.safe_dump(lock, sort_keys=True, allow_unicode=True), encoding="utf-8")
        tasks = self.state.tasks
        failed = sorted(name for name, record in tasks.items() if record.get("status") != "succeeded")
        summary = {
            "schema": "openocean.release-test-summary/v1",
            "releaseId": self.release_id,
            "status": "passed" if not failed else "failed",
            "tasks": {
                name: {
                    "status": record.get("status"),
                    "startedAt": record.get("startedAt"),
                    "finishedAt": record.get("finishedAt"),
                }
                for name, record in sorted(tasks.items())
            },
            "failed": failed,
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if failed:
            raise RuntimeError(f"cannot seal release with failed tasks: {', '.join(failed)}")
        expected_assets: set[str] = set()
        if self.release.products.native:
            for family in self.release.native_families:
                base = NATIVE_ASSET_NAMES[family]
                if "linux-x86_64" in self.release.native_platforms:
                    expected_assets.add(
                        f"{base}-{self.release_id}-linux-x86_64.tar.gz")
                if "windows-x86_64" in self.release.native_platforms:
                    expected_assets.add(
                        f"{base}-{self.release_id}-windows-x86_64.zip")
        if self.release.products.python:
            expected_assets.update({
                f"OpenOcean-Field-Python-{self.release_id}-linux-x86_64.tar.gz",
                f"OpenOcean-Field-Python-{self.release_id}-windows-x86_64.zip",
            })
        if self.release.products.matlab:
            expected_assets.add(
                f"OpenOcean-Field-Toolbox-{self.release_id}-win64.mltbx")
        actual_assets = {
            path.name for path in self.assets_dir.iterdir() if path.is_file()
        }
        if actual_assets != expected_assets:
            missing = sorted(expected_assets - actual_assets)
            unexpected = sorted(actual_assets - expected_assets)
            raise RuntimeError(
                "release asset set is incomplete; missing="
                f"{missing}, unexpected={unexpected}")
        files = []
        checksum_lines = []
        for path in sorted(self.assets_dir.iterdir()):
            if not path.is_file():
                continue
            digest = sha256_file(path)
            name = path.name
            kind = "matlab" if name.endswith(".mltbx") else (
                "python" if "-Python-" in name else "native")
            target_platform = "windows-x86_64" if (
                "windows-x86_64" in name or name.endswith("-win64.mltbx")) else "linux-x86_64"
            files.append({
                "path": name,
                "type": kind,
                "platform": target_platform,
                "bytes": path.stat().st_size,
                "sha256": digest,
            })
            checksum_lines.append(f"{digest}  {path.name}")
        manifest = {
            "schema": "openocean.release-manifest/v1",
            "releaseId": self.release_id,
            "files": files,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for path in (lock_path, manifest_path, summary_path):
            checksum_lines.append(f"{sha256_file(path)}  {path.name}")
        checksums_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
        if self.release.notes == "auto":
            notes_path.write_text(self._automatic_notes(lock), encoding="utf-8")
        else:
            source = (self.release.path.parent / self.release.notes).resolve()
            shutil.copy2(source, notes_path)
        self.state.document["sealed"] = True
        self.state.document["sealedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.state.save()

    def _automatic_notes(self, lock: Mapping[str, object]) -> str:
        """Describe the locked sources and compare with the last published lock."""
        current_key = _version_key(self.release_id)
        previous: tuple[tuple[int, int, int, int], str, Mapping[str, object]] | None = None
        releases = self.runner.storage("releases")
        if current_key is not None and releases.is_dir():
            for directory in releases.iterdir():
                key = _version_key(directory.name)
                if key is None or key >= current_key:
                    continue
                state_path = directory / "state.json"
                lock_path = directory / "release-lock.yaml"
                if not state_path.is_file() or not lock_path.is_file():
                    continue
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    candidate = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, yaml.YAMLError):
                    continue
                if state.get("published") is not True or not isinstance(candidate, Mapping):
                    continue
                if previous is None or key > previous[0]:
                    previous = (key, directory.name, candidate)

        lines = [
            f"# OpenOcean Field {self.release_id}",
            "",
            "Built and verified from the immutable commits in `release-lock.yaml`.",
            "",
            "## Source revisions",
            "",
        ]
        sources = lock.get("sources", {})
        previous_sources = previous[2].get("sources", {}) if previous else {}
        if not isinstance(sources, Mapping):
            sources = {}
        if not isinstance(previous_sources, Mapping):
            previous_sources = {}
        for name, raw in sorted(sources.items()):
            if not isinstance(raw, Mapping):
                continue
            repository = str(raw.get("repository", ""))
            commit = str(raw.get("commit", ""))
            current_link = f"https://github.com/{repository}/commit/{commit}"
            detail = f"[`{commit[:12]}`]({current_link})"
            old = previous_sources.get(name)
            if isinstance(old, Mapping):
                old_commit = str(old.get("commit", ""))
                if old_commit == commit:
                    detail += " (unchanged)"
                elif old_commit:
                    comparison = f"https://github.com/{repository}/compare/{old_commit}...{commit}"
                    detail += f" ([changes since v{previous[1]}]({comparison}))"
            lines.append(f"- `{name}`: {detail}")
        return "\n".join(lines) + "\n"

    def build(self) -> str:
        self.prepare()
        self.preflight()
        self.resolve_sources()
        self.checkout_sources()
        windows_selected = (
            self.release.products.matlab
            or (self.release.products.native and "windows-x86_64" in self.release.native_platforms)
            or (self.release.products.python and "windows-x86_64" in self.release.python_platforms)
        )
        guest_sources = ""
        try:
            if self.release.products.native and "linux-x86_64" in self.release.native_platforms:
                for family in self.release.native_families:
                    self._linux_native(family)
            if windows_selected:
                _, guest_sources = self._stage_windows_sources()
            if self.release.products.native and "windows-x86_64" in self.release.native_platforms:
                for family in self.release.native_families:
                    self._windows_native(family, guest_sources)
            if self.release.products.python:
                self._linux_python()
                self._windows_python(guest_sources)
            if self.release.products.matlab:
                self._windows_matlab(guest_sources)
            self._seal()
            assert self.logger is not None
            self.logger.event("release", "INFO", f"sealed release at {self.release_dir}")
            return self.release_id
        finally:
            if windows_selected:
                self._restore_vm()


def publish_release(
    release_id: str,
    runner: RunnerConfig,
    *,
    config: ReleaseConfig | None = None,
) -> None:
    release_dir = runner.storage("releases") / release_id
    state_path = release_dir / "state.json"
    lock_path = release_dir / "release-lock.yaml"
    config_path = release_dir / "release-config.yaml"
    manifest_path = release_dir / "manifest.json"
    checksums_path = release_dir / "SHA256SUMS"
    summary_path = release_dir / "test-summary.json"
    notes_path = release_dir / "release-notes.md"
    required = [state_path, lock_path, config_path, manifest_path, checksums_path, summary_path, notes_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"release is not sealed; missing: {', '.join(missing)}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if (state.get("schema") != "openocean.release-state/v1"
            or state.get("releaseId") != release_id
            or state.get("sealed") is not True):
        raise RuntimeError("release state is not sealed")
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    if (not isinstance(lock, Mapping) or lock.get("schema") != LOCK_SCHEMA
            or lock.get("releaseId") != release_id):
        raise RuntimeError("release lock identity is invalid")
    snapshot = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, Mapping):
        raise RuntimeError("sealed release config is invalid")
    release_values = snapshot.get("release")
    products = snapshot.get("products")
    sources = snapshot.get("sources")
    if (snapshot.get("schema") != "openocean.release/v1"
            or not isinstance(release_values, Mapping)
            or release_values.get("version") != release_id
            or not isinstance(products, Mapping)
            or not isinstance(sources, Mapping)):
        raise RuntimeError("sealed release config identity is invalid")
    expected_source_names = {
        name for name, value in sources.items()
        if isinstance(value, Mapping) and value.get("enabled", True) is True
    }
    native = products.get("native")
    python_product = products.get("python")
    matlab = products.get("matlab")
    field_runner = products.get("field_runner")
    if not all(isinstance(value, Mapping) for value in (
            native, python_product, matlab, field_runner)):
        raise RuntimeError("sealed product selection is invalid")
    native_enabled = native.get("enabled") is True
    python_enabled = python_product.get("enabled") is True
    matlab_enabled = matlab.get("enabled") is True
    native_platforms = native.get("platforms", [])
    native_families = native.get("families", [])
    python_platforms = python_product.get("platforms", [])
    if (not isinstance(native_platforms, list)
            or not isinstance(native_families, list)
            or not isinstance(python_platforms, list)):
        raise RuntimeError("sealed product matrix is invalid")
    expected_tasks = {"resolve"} | {
        f"checkout.{name}" for name in expected_source_names
    }
    expected_assets: dict[str, tuple[str, str]] = {}
    if native_enabled:
        for family in native_families:
            if family not in NATIVE_ASSET_NAMES:
                raise RuntimeError(f"sealed native family is invalid: {family}")
            base = NATIVE_ASSET_NAMES[family]
            if "linux-x86_64" in native_platforms:
                expected_tasks.add(f"linux.native.{family}")
                expected_assets[
                    f"{base}-{release_id}-linux-x86_64.tar.gz"
                ] = ("native", "linux-x86_64")
            if "windows-x86_64" in native_platforms:
                expected_tasks.add(f"windows.native.{family}")
                expected_assets[
                    f"{base}-{release_id}-windows-x86_64.zip"
                ] = ("native", "windows-x86_64")
    if python_enabled:
        if "linux-x86_64" in python_platforms:
            expected_tasks.add("linux.python")
            expected_assets[
                f"OpenOcean-Field-Python-{release_id}-linux-x86_64.tar.gz"
            ] = ("python", "linux-x86_64")
        if "windows-x86_64" in python_platforms:
            expected_tasks.add("windows.python")
            expected_assets[
                f"OpenOcean-Field-Python-{release_id}-windows-x86_64.zip"
            ] = ("python", "windows-x86_64")
    if matlab_enabled:
        expected_tasks.add("windows.matlab")
        expected_assets[
            f"OpenOcean-Field-Toolbox-{release_id}-win64.mltbx"
        ] = ("matlab", "windows-x86_64")
    windows_selected = (
        matlab_enabled
        or (native_enabled and "windows-x86_64" in native_platforms)
        or (python_enabled and "windows-x86_64" in python_platforms)
    )
    if windows_selected:
        expected_tasks.add("windows.stage-sources")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (summary.get("schema") != "openocean.release-test-summary/v1"
            or summary.get("releaseId") != release_id
            or summary.get("status") != "passed"
            or summary.get("failed") != []):
        raise RuntimeError("release tests did not pass")
    state_tasks = state.get("tasks")
    summary_tasks = summary.get("tasks")
    if not isinstance(state_tasks, Mapping) or not isinstance(summary_tasks, Mapping):
        raise RuntimeError("release task records are invalid")
    if set(state_tasks) != expected_tasks:
        raise RuntimeError("sealed release task set differs from the selected matrix")
    if set(state_tasks) != set(summary_tasks):
        raise RuntimeError("release state and test summary task sets differ")
    for name, record in state_tasks.items():
        if (not isinstance(record, Mapping)
                or record.get("status") != "succeeded"
                or not isinstance(record.get("inputSha256"), str)
                or not isinstance(record.get("outputs"), Mapping)):
            raise RuntimeError(f"release task is incomplete: {name}")
        summarized = summary_tasks[name]
        if not isinstance(summarized, Mapping) or summarized.get("status") != "succeeded":
            raise RuntimeError(f"release summary task is incomplete: {name}")
    actual_config_sha = __import__("hashlib").sha256(config_path.read_bytes()).hexdigest()
    if lock.get("configSha256") != actual_config_sha:
        raise RuntimeError("sealed release config hash differs from lock")
    if config is not None:
        supplied = json.loads(json.dumps(config.document))
        supplied["release"]["version"] = release_id
        if supplied != snapshot:
            raise RuntimeError("supplied release config differs from the sealed snapshot")
    locked_sources = lock.get("sources")
    if not isinstance(locked_sources, Mapping):
        raise RuntimeError("release lock source records are invalid")
    if set(locked_sources) != expected_source_names:
        raise RuntimeError("release lock source set differs from the sealed config")
    for name in expected_source_names:
        configured = sources[name]
        locked = locked_sources[name]
        if (not isinstance(configured, Mapping) or not isinstance(locked, Mapping)
                or locked.get("repository") != configured.get("repository")
                or locked.get("requestedRef") != configured.get("ref")
                or not re.fullmatch(r"[0-9a-f]{40}", str(locked.get("commit", "")))):
            raise RuntimeError(f"release lock source is invalid: {name}")
    expected_matrix = {
        "nativePlatforms": native_platforms if native_enabled else [],
        "pythonPlatforms": python_platforms if python_enabled else [],
        "pythonVersions": (
            python_product.get("versions", []) if python_enabled else []),
        "matlabPlatform": "windows-x86_64" if matlab_enabled else None,
        "fieldRunnerBackends": (
            list(BACKENDS) if field_runner.get("enabled") is True else []),
    }
    if lock.get("matrix") != expected_matrix:
        raise RuntimeError("release lock matrix differs from the sealed config")
    orchestrator = lock.get("orchestrator")
    if (not isinstance(orchestrator, Mapping)
            or orchestrator.get("repository") != RELEASE_REPOSITORY
            or not re.fullmatch(r"[0-9a-f]{40}", str(orchestrator.get("commit", "")))):
        raise RuntimeError("release lock orchestrator identity is invalid")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != "openocean.release-manifest/v1"
            or manifest.get("releaseId") != release_id
            or not isinstance(manifest.get("files"), list)):
        raise RuntimeError("release manifest identity is invalid")
    assets: list[Path] = []
    manifest_names: set[str] = set()
    for item in manifest["files"]:
        if not isinstance(item, Mapping):
            raise RuntimeError("release manifest contains an invalid asset record")
        relative = item.get("path", "")
        if (not isinstance(relative, str) or not relative
                or Path(relative).name != relative or relative in manifest_names):
            raise RuntimeError(f"manifest asset path is invalid: {relative}")
        manifest_names.add(relative)
        path = (release_dir / "assets" / relative).resolve()
        if not path.is_relative_to((release_dir / "assets").resolve()) or not path.is_file():
            raise RuntimeError(f"manifest asset is missing or unsafe: {relative}")
        if item.get("bytes") != path.stat().st_size:
            raise RuntimeError(f"manifest asset size mismatch: {relative}")
        expected_identity = expected_assets.get(relative)
        if expected_identity is None:
            raise RuntimeError(f"manifest contains an unselected asset: {relative}")
        if (item.get("type"), item.get("platform")) != expected_identity:
            raise RuntimeError(f"manifest asset identity mismatch: {relative}")
        if sha256_file(path) != item.get("sha256"):
            raise RuntimeError(f"manifest checksum mismatch: {relative}")
        assets.append(path)
    actual_asset_names = {
        path.name for path in (release_dir / "assets").iterdir()
        if path.is_file()
    }
    if actual_asset_names != manifest_names:
        raise RuntimeError("manifest file set differs from the sealed asset directory")
    if manifest_names != set(expected_assets):
        raise RuntimeError("manifest asset set differs from the selected matrix")
    checksum_entries: dict[str, str] = {}
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise RuntimeError("SHA256SUMS contains an invalid record")
        if parts[1] in checksum_entries:
            raise RuntimeError(f"SHA256SUMS contains a duplicate path: {parts[1]}")
        checksum_entries[parts[1]] = parts[0]
    checked_paths = assets + [lock_path, manifest_path, summary_path]
    expected_checksum_names = {path.name for path in checked_paths}
    if set(checksum_entries) != expected_checksum_names:
        raise RuntimeError("SHA256SUMS file set differs from the sealed release")
    for path in checked_paths:
        if sha256_file(path) != checksum_entries[path.name]:
            raise RuntimeError(f"SHA256SUMS mismatch: {path.name}")
    assets += [lock_path, manifest_path, checksums_path, summary_path]
    token_env = runner.credential_env("github_publish_token_env")
    target = orchestrator["commit"]
    title_template = release_values.get("title", "OpenOcean Field {version}")
    title = str(title_template).format(version=release_id)
    create_public_release(
        repository=RELEASE_REPOSITORY,
        tag=f"v{release_id}",
        target_sha=target,
        title=title,
        notes_file=notes_path,
        assets=assets,
        token_env=token_env,
    )
    state["published"] = True
    state["publishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    state["publishedTag"] = f"v{release_id}"
    temporary = state_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(state_path)
