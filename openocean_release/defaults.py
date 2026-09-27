"""Code-owned release defaults; operators edit release.local.py."""

from __future__ import annotations

from typing import Any

from .config import BACKENDS, NATIVE_FAMILIES, RELEASE_SCHEMA

DEFAULT_REFS = {
    "field_core": "1a2d384f478b321d7311a32ee293e076ee5fb5ba",
    "ray_mode": "cb36802e869b022e0a4e9dc90a1162811f7a9b84",
    "normal_mode": "b9c74d61a03c973ff8a201d1d1455523213e1c4e",
    "pe": "b9efda4bc1c09de6a00d80d9dcaabe1dda06433d",
    "toolbox": "6a051ca3ea338f0b426ccca25f2b04428186ed1b",
    "wi": "5028741e9827729cd1b8394da545843c141ea627",
    "couple": "c7f6ce321e4a017070b101979a4b11e92d5c4089",
}
SOURCE_REPOSITORIES = {
    "field_core": "OpenOceanAcoustic/OpenOcean-Field-Core",
    "ray_mode": "OpenOceanAcoustic/OpenOcean-Field-RayMode",
    "normal_mode": "OpenOceanAcoustic/OpenOcean-Field-NormalMode",
    "pe": "OpenOceanAcoustic/OpenOcean-Field-PE",
    "toolbox": "OpenOceanAcoustic/OpenOcean-Field-Toolbox",
    "wi": "OpenOceanAcoustic/OpenOcean-Field-WI",
    "couple": "OpenOceanAcoustic/OpenOcean-Field-Couple",
}


def release_document() -> dict[str, Any]:
    """Return a fresh internal contract, narrowed by the typed operator plan."""
    return {
        "schema": RELEASE_SCHEMA,
        "release": {
            "version": "auto",
            "tag": "OpenOcean-Field-V{version}",
            "profile": "full",
            "title": "OpenOcean-Field-V{version}",
            "notes": "auto",
        },
        "sources": {
            name: {"repository": repository, "ref": DEFAULT_REFS[name], "enabled": True}
            for name, repository in SOURCE_REPOSITORIES.items()
        },
        "products": {
            "native": {
                "enabled": True,
                "platforms": ["windows-x86_64"],
                "families": list(NATIVE_FAMILIES),
                "linkage": ["shared", "static"],
                "standalone_executables": True,
            },
            "python": {
                "enabled": True,
                "platforms": ["linux-x86_64", "windows-x86_64"],
                "versions": ["cp310", "cp311", "cp312", "cp313", "cp314"],
                "distribution": "openocean-field",
                "import_package": "openocean_field.sdk",
                "installer": True,
            },
            "matlab": {
                "enabled": True,
                "platform": "windows-x86_64",
                "minimum_release": "R2023a",
                "test_release": "R2025b",
                "toolbox_identifier": "openocean-field-tools",
                "embed_native_runtime": True,
            },
            "field_runner": {
                "enabled": True,
                "publish_asset": False,
                "backends": list(BACKENDS),
            },
        },
        "output": {
            "checksums": "sha256",
            "include_lock_file": True,
            "include_manifest": True,
            "include_test_summary": True,
            "include_raw_logs": False,
        },
    }
