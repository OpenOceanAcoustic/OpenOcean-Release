#!/usr/bin/env python3
"""Daily operator entry point; legacy commands remain available."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from openocean_release.config import ConfigurationError
from openocean_release.plan import ROOT, config_for_request, load_local
from openocean_release.request_runner import run_request


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if not args or args in (["-h"], ["--help"]):
            print("OpenOcean Release\n"
                  "  python3 main.py init              create ignored release.local.py\n"
                  "  python3 main.py plan              show choices without server config\n"
                  "  python3 main.py submit preview    build a private server preview\n"
                  "  python3 main.py submit release    seal; publish only if publish(True)\n"
                  "Edit release.local.py in your IDE. See README.md for credentials and paths.")
            return 0
        if args == ["init"]:
            target = ROOT / "release.local.py"
            if target.exists():
                raise ConfigurationError("release.local.py already exists; edit it in your IDE")
            shutil.copyfile(ROOT / "release.local.example.py", target)
            print(f"Created {target}")
            return 0
        if args == ["plan"]:
            plan = load_local()
            valid = 0
            for kind in ("preview", "release"):
                try:
                    request = plan.request(kind)
                except ConfigurationError as error:
                    print(f"{kind}: unavailable ({error})")
                    continue
                valid += 1
                print(f"{kind}: " + json.dumps({key: request[key] for key in (
                    "version", "native", "native_platforms", "python_platforms", "matlab", "build", "publish", "release_id")}, ensure_ascii=False))
                if request["build"]:
                    config = config_for_request(request, kind)
                    print("Source refs:")
                    for name, source in config.sources.items():
                        if source.enabled:
                            print(f"  {name}: {source.ref}")
                print(f"Release notes: {request['notes'] or 'automatic'}")
            print("Server paths and credentials are supplied by ci_server when submitted.")
            return 0 if valid else 2
        if len(args) == 2 and args[0] == "submit" and args[1] in {"preview", "release"}:
            kind = args[1]
            request = load_local().request(kind)
            payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
            subprocess.run(["gh", "workflow", "run", f"{kind}.yml", "--repo",
                            "OpenOceanAcoustic/OpenOcean-Release", "--ref", "main",
                            "-f", f"request={payload}"], check=True)
            print(f"Submitted {kind}. Check the Actions run for the sealed directory and checksums.")
            return 0
        if len(args) in {2, 3} and args[0] == "run-request" and args[1] in {"preview", "release"} and (len(args) == 2 or args[2] == "publish"):
            raw = os.environ.get("OPENOCEAN_RELEASE_REQUEST")
            if not raw:
                raise ConfigurationError("OPENOCEAN_RELEASE_REQUEST is missing")
            release_id = run_request(args[1], raw, stage="publish" if len(args) == 3 else "build")
            if os.environ.get("GITHUB_OUTPUT") and len(args) == 2:
                with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
                    output.write(f"release_id={release_id}\n")
            return 0
        from openocean_release.cli import main as legacy_main
        return legacy_main(args)
    except subprocess.CalledProcessError as error:
        if args and args[0] == "submit":
            message = "GitHub workflow submission failed; check gh auth status and repository write access"
        else:
            message = f"command failed with exit code {error.returncode}; see the build log"
        print(f"openocean-release: {message}", file=sys.stderr)
        return 2
    except (ConfigurationError, RuntimeError, OSError, ValueError) as error:
        print(f"openocean-release: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
