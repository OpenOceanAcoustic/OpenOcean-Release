"""Strict public release and private runner configuration models."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import string
from typing import Any, Mapping

import yaml


RELEASE_SCHEMA = "openocean.release/v1"
RUNNER_SCHEMA = "openocean.runner/v1"
LOCK_SCHEMA = "openocean.release-lock/v1"
SUPPORTED_PROFILES = {"full", "native", "python", "matlab"}
SUPPORTED_PLATFORMS = {"linux-x86_64", "windows-x86_64"}
SUPPORTED_PYTHONS = {"cp310", "cp311", "cp312", "cp313", "cp314"}
REQUIRED_SOURCES = ("field_core", "ray_mode", "normal_mode", "pe", "toolbox")
NATIVE_FAMILIES = ("field_core", "ray_mode", "normal_mode", "pe")
BACKENDS = (
    "ray_mode.bellhop.2d",
    "ray_mode.bellhop.3d",
    "ray_mode.bellhop.nx2d",
    "normal_mode.kraken",
    "normal_mode.krakenc",
    "pe.ram",
    "pe.ramgeo",
    "pe.rams",
)
VERSION_RE = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+\.[1-9][0-9]*$")


class ConfigurationError(ValueError):
    """Raised when a release contract cannot be satisfied."""


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{label} must be a mapping")
    return dict(value)


def _keys(document: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise ConfigurationError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigurationError(f"{label} must be a string list")
    if len(set(value)) != len(value):
        raise ConfigurationError(f"{label} contains duplicates")
    return tuple(value)


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigurationError(f"configuration file does not exist: {path}") from error
    except yaml.YAMLError as error:
        raise ConfigurationError(f"invalid YAML in {path}: {error}") from error
    return _mapping(document, str(path))


@dataclass(frozen=True)
class Source:
    name: str
    repository: str
    ref: str
    enabled: bool = True


@dataclass(frozen=True)
class ProductSelection:
    native: bool
    python: bool
    matlab: bool
    field_runner: bool


@dataclass(frozen=True)
class ReleaseConfig:
    path: Path
    document: dict[str, Any]
    version: str
    profile: str
    title: str
    notes: str
    sources: dict[str, Source]
    products: ProductSelection
    native_platforms: tuple[str, ...]
    native_families: tuple[str, ...]
    python_platforms: tuple[str, ...]
    python_versions: tuple[str, ...]
    matlab_test_release: str

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        profile_override: str | None = None,
        version_override: str | None = None,
        ref_overrides: Mapping[str, str] | None = None,
    ) -> "ReleaseConfig":
        path = path.resolve()
        document = load_yaml(path)
        _keys(document, {"schema", "release", "sources", "products", "output"}, "release config")
        if document.get("schema") != RELEASE_SCHEMA:
            raise ConfigurationError(f"schema must be {RELEASE_SCHEMA}")

        release = _mapping(document.get("release"), "release")
        _keys(release, {"version", "profile", "title", "notes"}, "release")
        profile = profile_override or str(release.get("profile", "full"))
        if profile not in SUPPORTED_PROFILES:
            raise ConfigurationError(f"unsupported profile: {profile}")
        version = version_override or str(release.get("version", "auto"))
        if version != "auto" and not VERSION_RE.fullmatch(version):
            raise ConfigurationError("release.version must be auto or YYYY.M.D.N")
        title = release.get("title", "OpenOcean Field {version}")
        if not isinstance(title, str) or not title.strip():
            raise ConfigurationError("release.title must be a nonempty string")
        try:
            title_fields = {
                field_name for _, field_name, _, _ in string.Formatter().parse(title)
                if field_name is not None
            }
        except ValueError as error:
            raise ConfigurationError(f"release.title is invalid: {error}") from error
        if title_fields - {"version"}:
            raise ConfigurationError(
                "release.title supports only the {version} placeholder")
        notes = release.get("notes", "auto")
        if not isinstance(notes, str) or not notes.strip():
            raise ConfigurationError("release.notes must be auto or a Markdown path")
        if notes != "auto":
            notes_path = Path(notes)
            resolved_notes = (path.parent / notes_path).resolve()
            if (notes_path.is_absolute()
                    or not resolved_notes.is_relative_to(path.parent)
                    or resolved_notes.suffix.lower() not in {".md", ".markdown"}
                    or not resolved_notes.is_file()):
                raise ConfigurationError(
                    "release.notes must reference a Markdown file inside the config repository")

        source_values = _mapping(document.get("sources"), "sources")
        _keys(
            source_values,
            set(REQUIRED_SOURCES) | {"wi", "couple"},
            "sources",
        )
        sources: dict[str, Source] = {}
        overrides = dict(ref_overrides or {})
        for name, value in source_values.items():
            item = _mapping(value, f"sources.{name}")
            _keys(item, {"repository", "ref", "enabled"}, f"sources.{name}")
            repository = item.get("repository")
            ref = overrides.pop(name, str(item.get("ref", "main")))
            enabled = item.get("enabled", True)
            if not isinstance(repository, str) or repository.count("/") != 1:
                raise ConfigurationError(f"sources.{name}.repository must be owner/name")
            if not isinstance(ref, str) or not ref.strip():
                raise ConfigurationError(f"sources.{name}.ref must not be empty")
            if not isinstance(enabled, bool):
                raise ConfigurationError(f"sources.{name}.enabled must be boolean")
            if name in {"wi", "couple"} and enabled:
                raise ConfigurationError(f"{name} release adapter not implemented")
            sources[name] = Source(name, repository, ref, enabled)
        if overrides:
            raise ConfigurationError(f"unknown --ref sources: {', '.join(sorted(overrides))}")
        missing = [name for name in REQUIRED_SOURCES if name not in sources]
        if missing:
            raise ConfigurationError(f"missing required sources: {', '.join(missing)}")
        disabled = [name for name in REQUIRED_SOURCES if not sources[name].enabled]
        if disabled:
            raise ConfigurationError(f"required sources are disabled: {', '.join(disabled)}")

        product_values = _mapping(document.get("products"), "products")
        _keys(product_values, {"native", "python", "matlab", "field_runner"}, "products")
        profile_defaults = {
            "full": (True, True, True),
            "native": (True, False, False),
            "python": (False, True, False),
            "matlab": (False, False, True),
        }[profile]

        native = _mapping(product_values.get("native", {}), "products.native")
        _keys(native, {"enabled", "platforms", "families", "linkage", "standalone_executables"}, "products.native")
        python = _mapping(product_values.get("python", {}), "products.python")
        _keys(python, {"enabled", "platforms", "versions", "distribution", "import_package", "installer"}, "products.python")
        matlab = _mapping(product_values.get("matlab", {}), "products.matlab")
        _keys(matlab, {"enabled", "platform", "minimum_release", "test_release", "toolbox_identifier", "embed_native_runtime"}, "products.matlab")
        runner = _mapping(product_values.get("field_runner", {}), "products.field_runner")
        _keys(runner, {"enabled", "publish_asset", "backends"}, "products.field_runner")

        def enabled(item: Mapping[str, Any], default: bool) -> bool:
            if profile_override is not None:
                return default
            result = item.get("enabled", default)
            if not isinstance(result, bool):
                raise ConfigurationError("product enabled values must be boolean")
            return result

        selection = ProductSelection(
            enabled(native, profile_defaults[0]),
            enabled(python, profile_defaults[1]),
            enabled(matlab, profile_defaults[2]),
            enabled(runner, profile_defaults[1] or profile_defaults[2]),
        )
        native_platforms = _strings(native.get("platforms", []), "products.native.platforms")
        python_platforms = _strings(python.get("platforms", []), "products.python.platforms")
        python_versions = _strings(python.get("versions", []), "products.python.versions")
        native_families = _strings(native.get("families", []), "products.native.families")
        if selection.native and (set(native_platforms) - SUPPORTED_PLATFORMS):
            raise ConfigurationError("native contains unsupported platforms")
        if selection.native and tuple(native_families) != NATIVE_FAMILIES:
            raise ConfigurationError("native.families must contain field_core, ray_mode, normal_mode, pe in order")
        if selection.native and native.get("linkage") != ["shared", "static"]:
            raise ConfigurationError("native.linkage must be [shared, static]")
        if selection.native and native.get("standalone_executables") is not True:
            raise ConfigurationError("native.standalone_executables must be true")
        if selection.python and set(python_platforms) != SUPPORTED_PLATFORMS:
            raise ConfigurationError("python release requires Linux and Windows x86_64")
        if selection.python and set(python_versions) != SUPPORTED_PYTHONS:
            raise ConfigurationError("python release requires cp310 through cp314")
        if selection.python and (python.get("distribution") != "openocean-field" or python.get("import_package") != "openocean_field.sdk"):
            raise ConfigurationError("python distribution/import package contract changed")
        if selection.python and python.get("installer") is not True:
            raise ConfigurationError("python.installer must be true")
        if selection.matlab:
            expected_matlab = {
                "platform": "windows-x86_64",
                "minimum_release": "R2023a",
                "test_release": "R2025b",
                "toolbox_identifier": "48c2d99b-c630-5cdb-8f78-b7844ec5b673",
                "embed_native_runtime": True,
            }
            for key, expected in expected_matlab.items():
                if matlab.get(key) != expected:
                    raise ConfigurationError(f"products.matlab.{key} must be {expected!r}")
        if runner.get("publish_asset") is not False:
            raise ConfigurationError(
                "products.field_runner.publish_asset must be false")
        if (selection.python or selection.matlab) and not selection.field_runner:
            raise ConfigurationError("Python and MATLAB products require field_runner.enabled=true")
        if selection.field_runner and not (selection.python or selection.matlab):
            raise ConfigurationError(
                "field_runner requires a Python or MATLAB product so its two-platform gate runs")
        if tuple(runner.get("backends", ())) != BACKENDS:
            raise ConfigurationError("FieldRunner must contain the fixed eight-backend contract")

        output = _mapping(document.get("output"), "output")
        _keys(output, {"checksums", "include_lock_file", "include_manifest", "include_test_summary", "include_raw_logs"}, "output")
        expected_output = {
            "checksums": "sha256",
            "include_lock_file": True,
            "include_manifest": True,
            "include_test_summary": True,
            "include_raw_logs": False,
        }
        for key, expected in expected_output.items():
            if output.get(key) != expected:
                raise ConfigurationError(f"output.{key} must be {expected!r}")

        normalized = deepcopy(document)
        normalized["release"]["version"] = version
        normalized["release"]["profile"] = profile
        normalized["products"]["native"]["enabled"] = selection.native
        normalized["products"]["python"]["enabled"] = selection.python
        normalized["products"]["matlab"]["enabled"] = selection.matlab
        normalized["products"]["field_runner"]["enabled"] = selection.field_runner
        for name, source in sources.items():
            normalized["sources"][name]["ref"] = source.ref
        return cls(
            path, normalized, version, profile,
            title, notes, sources, selection,
            native_platforms, native_families, python_platforms, python_versions,
            str(matlab.get("test_release", "")),
        )

    def canonical_bytes(self) -> bytes:
        return yaml.safe_dump(self.document, sort_keys=True, allow_unicode=True).encode("utf-8")

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class RunnerConfig:
    path: Path
    document: dict[str, Any]

    @classmethod
    def load(cls, path: Path | None = None) -> "RunnerConfig":
        selected = path or (Path(os.environ["OPENOCEAN_RUNNER_CONFIG"]) if os.environ.get("OPENOCEAN_RUNNER_CONFIG") else None)
        if selected is None:
            raise ConfigurationError("set OPENOCEAN_RUNNER_CONFIG to the private runner YAML")
        selected = selected.expanduser().resolve()
        document = load_yaml(selected)
        _keys(
            document,
            {"schema", "execution", "storage", "linux", "windows", "credentials", "logging"},
            "runner config",
        )
        if document.get("schema") != RUNNER_SCHEMA:
            raise ConfigurationError(f"runner schema must be {RUNNER_SCHEMA}")
        for section in ("execution", "storage", "linux", "windows", "credentials"):
            _mapping(document.get(section), f"runner.{section}")
        execution = _mapping(document["execution"], "runner.execution")
        _keys(execution, {"build_user", "require_initial_sudo"}, "runner.execution")
        storage = _mapping(document["storage"], "runner.storage")
        _keys(storage, {"root", "linux", "windows", "cache", "staging", "releases"}, "runner.storage")
        linux = _mapping(document["linux"], "runner.linux")
        _keys(linux, {"engine", "image", "inherit_proxy"}, "runner.linux")
        if linux.get("engine") != "docker":
            raise ConfigurationError("runner.linux.engine must be docker")
        image = linux.get("image")
        if not isinstance(image, str) or "@sha256:" not in image:
            raise ConfigurationError("runner.linux.image must use an immutable @sha256 digest")
        windows = _mapping(document["windows"], "runner.windows")
        _keys(windows, {
            "vm_controller", "powershell_runner", "shared_host_root",
            "shared_guest_root", "ssh_host", "ssh_port", "ssh_user",
            "ssh_private_key", "ssh_known_hosts", "build_python", "wheelhouse",
            "cibuildwheel_cache", "matlab", "inherit_proxy",
            "restore_previous_vm_state",
        }, "runner.windows")
        credentials = _mapping(document["credentials"], "runner.credentials")
        _keys(credentials, {"source_read_token_env", "github_publish_token_env"}, "runner.credentials")
        if "logging" in document:
            logging = _mapping(document["logging"], "runner.logging")
            _keys(logging, {"live", "text", "jsonl", "redact_environment"}, "runner.logging")
        return cls(selected, document)

    def section(self, name: str) -> dict[str, Any]:
        return _mapping(self.document[name], f"runner.{name}")

    def storage(self, name: str) -> Path:
        value = self.section("storage").get(name)
        if not isinstance(value, str) or not value:
            raise ConfigurationError(f"runner.storage.{name} must be a path")
        return Path(value).expanduser().resolve()

    def credential_env(self, name: str) -> str:
        value = self.section("credentials").get(name)
        if not isinstance(value, str) or not value:
            raise ConfigurationError(f"runner.credentials.{name} must name an environment variable")
        return value


def parse_ref_overrides(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ConfigurationError(f"--ref must use source=ref: {value}")
        source, ref = value.split("=", 1)
        if not source or not ref or source in result:
            raise ConfigurationError(f"invalid or duplicate --ref: {value}")
        result[source] = ref
    return result
