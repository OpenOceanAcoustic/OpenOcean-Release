"""Small, typed operator API and the public request sent to Actions."""

from __future__ import annotations

from copy import deepcopy
from enum import Enum
import importlib.util
import json
from pathlib import Path
import re
from typing import Any

from .config import ConfigurationError, NATIVE_FAMILIES, REQUIRED_SOURCES, ReleaseConfig
from .defaults import DEFAULT_REFS, release_document

ROOT = Path(__file__).resolve().parents[1]
REQUEST_SCHEMA = "openocean.release-request/v1"


def _valid_ref(ref: Any) -> bool:
    return (isinstance(ref, str) and 0 < len(ref) <= 200 and ref.strip() == ref
            and not re.search(r"[\x00-\x20\x7f]", ref))


class Model(str, Enum):
    FIELD_CORE = "field_core"
    RAY_MODE = "ray_mode"
    NORMAL_MODE = "normal_mode"
    PE = "pe"
    TOOLBOX = "toolbox"
    WI = "wi"
    COUPLE = "couple"


class Platform(str, Enum):
    LINUX = "linux-x86_64"
    WINDOWS = "windows-x86_64"


class ReleasePlan:
    def __init__(self) -> None:
        self._refs = dict(DEFAULT_REFS)
        self._native: tuple[str, ...] = ()
        self._native_platforms: tuple[str, ...] = (Platform.WINDOWS.value,)
        self._python: tuple[str, ...] = ()
        self._matlab = False
        self._version = "auto"
        self._notes = ""
        self._publish = False
        self._build = True
        self._release_id: str | None = None

    def ref(self, model: Model, ref: str) -> "ReleasePlan":
        if not isinstance(model, Model) or not _valid_ref(ref):
            raise ConfigurationError("ref(model, ref) requires a model enum and a nonempty Git ref")
        self._refs[model.value] = ref.strip()
        return self

    def native(self, *models: Model, platforms: tuple[Platform, ...] = (Platform.WINDOWS,)) -> "ReleasePlan":
        names = [model.value for model in models if isinstance(model, Model)]
        if len(names) != len(models) or set(names) - set(NATIVE_FAMILIES) or len(names) != len(set(names)):
            raise ConfigurationError("native() requires distinct native model enums")
        self._native = tuple(name for name in NATIVE_FAMILIES if name in names)
        self._native_platforms = self._platforms(platforms)
        return self

    def python(self, *platforms: Platform) -> "ReleasePlan":
        self._python = self._platforms(platforms or (Platform.LINUX, Platform.WINDOWS))
        return self

    def matlab(self, enabled: bool = True) -> "ReleasePlan":
        self._matlab = self._boolean(enabled)
        return self

    def version(self, value: str) -> "ReleasePlan":
        self._version = value
        return self

    def notes(self, markdown: str) -> "ReleasePlan":
        if not isinstance(markdown, str) or len(markdown) > 30000:
            raise ConfigurationError("release notes must be Markdown under 30000 characters")
        self._notes = markdown
        return self

    def publish(self, enabled: bool = False) -> "ReleasePlan":
        self._publish = self._boolean(enabled)
        return self

    def build(self, enabled: bool = True) -> "ReleasePlan":
        self._build = self._boolean(enabled)
        return self

    def existing_release(self, release_id: str) -> "ReleasePlan":
        self._release_id = release_id
        self._build = False
        return self

    @staticmethod
    def _boolean(value: bool) -> bool:
        if not isinstance(value, bool):
            raise ConfigurationError("expected true or false")
        return value

    @staticmethod
    def _platforms(values: tuple[Platform, ...]) -> tuple[str, ...]:
        if not values or not all(isinstance(item, Platform) for item in values):
            raise ConfigurationError("platforms must contain Platform enums")
        result = tuple(dict.fromkeys(item.value for item in values))
        if len(result) != len(values):
            raise ConfigurationError("duplicate platform")
        return result

    def request(self, kind: str) -> dict[str, Any]:
        request = {
            "schema": REQUEST_SCHEMA,
            "kind": kind,
            "version": self._version,
            "refs": self._refs,
            "native": list(self._native),
            "native_platforms": list(self._native_platforms) if self._native else [],
            "python_platforms": list(self._python),
            "matlab": self._matlab,
            "notes": self._notes,
            "build": self._build,
            "publish": self._publish,
            "release_id": self._release_id,
        }
        validate_request(request, kind)
        if self._build:
            unused = sorted(name for name, ref in self._refs.items()
                            if ref != DEFAULT_REFS[name] and name not in required_models(request))
            if unused:
                raise ConfigurationError("ref was changed for a model outside the selected products: "
                                         + ", ".join(unused))
        return request


def validate_request(value: Any, kind: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema", "kind", "version", "refs", "native", "native_platforms",
        "python_platforms", "matlab", "notes", "build", "publish", "release_id",
    } or value.get("schema") != REQUEST_SCHEMA or value.get("kind") != kind:
        raise ConfigurationError("invalid release request schema or workflow kind")
    if kind not in {"preview", "release"}:
        raise ConfigurationError("workflow kind must be preview or release")
    if not isinstance(value["refs"], dict) or set(value["refs"]) != set(REQUIRED_SOURCES):
        raise ConfigurationError("refs must name every model")
    if any(not _valid_ref(ref) for ref in value["refs"].values()):
        raise ConfigurationError("invalid source ref")
    if not isinstance(value["version"], str) or not re.fullmatch(r"auto|(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)|[1-9][0-9]*\.[0-9]+\.[0-9]+\.[1-9][0-9]*", value["version"]):
        raise ConfigurationError("version must be auto, X.Y.Z or YYYY.M.D.N")
    native, native_platforms, python_platforms = (value[name] for name in ("native", "native_platforms", "python_platforms"))
    if (not isinstance(native, list) or not all(isinstance(item, str) for item in native)
            or tuple(name for name in NATIVE_FAMILIES if name in native) != tuple(native)):
        raise ConfigurationError("native must be an ordered subset of native models")
    allowed_platforms = {item.value for item in Platform}
    for name, platforms in (("native_platforms", native_platforms), ("python_platforms", python_platforms)):
        if (not isinstance(platforms, list)
                or any(not isinstance(item, str) or item not in allowed_platforms for item in platforms)
                or len(platforms) != len(set(platforms))):
            raise ConfigurationError(f"invalid {name}")
    if bool(native) != bool(native_platforms):
        raise ConfigurationError("native models and platforms must both be selected")
    if not isinstance(value["matlab"], bool) or not isinstance(value["build"], bool) or not isinstance(value["publish"], bool):
        raise ConfigurationError("matlab, build and publish must be booleans")
    if not isinstance(value["notes"], str) or len(value["notes"]) > 30000:
        raise ConfigurationError("invalid release notes")
    release_id = value["release_id"]
    if release_id is not None and (not isinstance(release_id, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?", release_id)):
        raise ConfigurationError("invalid existing release ID")
    if kind == "preview":
        if not value["build"] or value["publish"] or release_id is not None:
            raise ConfigurationError("preview must build and cannot publish an existing release")
    elif value["build"]:
        if release_id is not None or not (native or python_platforms or value["matlab"]):
            raise ConfigurationError("build requires selected products and no existing release ID")
    elif not value["publish"] or release_id is None:
        raise ConfigurationError("build(False) requires publish(True) and existing_release(id)")
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 60000:
        raise ConfigurationError("request exceeds the Actions input size limit")
    return deepcopy(value)


def load_local(path: Path = ROOT / "release.local.py") -> ReleasePlan:
    if not path.is_file():
        raise ConfigurationError("release.local.py is missing; run python3 main.py init")
    spec = importlib.util.spec_from_file_location("openocean_local_plan", path)
    if spec is None or spec.loader is None:
        raise ConfigurationError("cannot import release.local.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan = getattr(module, "plan", None)
    if not isinstance(plan, ReleasePlan):
        raise ConfigurationError("release.local.py must define plan = ReleasePlan()")
    return plan


def required_models(request: dict[str, Any]) -> set[str]:
    required = (set(REQUIRED_SOURCES) if (request["python_platforms"] or request["matlab"])
                else set(request["native"]))
    if "wi" in request["native"] and Platform.WINDOWS.value in request["native_platforms"]:
        required.add("toolbox")
    return required


def config_for_request(request: dict[str, Any], kind: str) -> ReleaseConfig:
    validate_request(request, kind)
    document = release_document()
    document["release"].update({"version": request["version"], "profile": "custom", "notes": "auto", "plan_kind": kind})
    document["release"].pop("notes_text", None)
    if request["notes"].strip():
        document["release"]["notes_text"] = request["notes"]
    required = required_models(request)
    for name, item in document["sources"].items():
        item["ref"] = request["refs"][name]
        item["enabled"] = name in required
    products = document["products"]
    products["native"].update(enabled=bool(request["native"]), families=request["native"], platforms=request["native_platforms"])
    products["python"].update(enabled=bool(request["python_platforms"]), platforms=request["python_platforms"])
    products["matlab"]["enabled"] = request["matlab"]
    products["field_runner"]["enabled"] = bool(request["python_platforms"] or request["matlab"])
    return ReleaseConfig.load(ROOT / "main.py", document_override=document)
