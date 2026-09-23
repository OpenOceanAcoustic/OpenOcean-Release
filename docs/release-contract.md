# Release contract

The supported sources are FieldCore, RayMode, NormalMode, PE, WI, Couple, and
Toolbox. The unified runtime registers ten backends, including `wi.oast` and
`couple`. Every model family supplies a native SDK and Python provider; WI and
Couple are also accessible through the MATLAB and Python Toolbox builders.

Every build resolves source refs to immutable commit SHAs before checkout. The
sealed directory under `storage.releases/<release-id>` contains:

```text
release-config.yaml
release-lock.yaml
manifest.json
SHA256SUMS
test-summary.json
state.json
release-notes.md
assets/
logs/
```

`state.json` stores task input hashes and output hashes. `--resume` only reuses
a task when both match. `--rebuild TASK` invalidates that task explicitly.
Logs stay on the runner and are never attached to the GitHub Release.

The checked-in 1.0.0 full profile produces six Windows native packages,
one Python SDK bundle for each of Linux and Windows, and one Windows MATLAB
bundle: nine product assets. Linux native libraries are not public assets in
this release. Native packages contain shared/static libraries, applicable
executables, headers, licenses, dependency notes, and CMake metadata. Each
Python bundle contains a pure facade wheel plus FieldCore, Bellhop, NormalMode,
PE, WI, and Couple native wheels for CPython 3.10 through 3.14, with an
ABI-selecting `install.py`. Couple's FieldCore provider is a CPython extension,
so this SDK uses CPython-specific Couple wheels; its standalone ctypes-only
build can still produce a `py3-none` wheel. FieldRunner is built and tested as
an internal runtime and has no separate customer asset. WASM is not a public
asset in this release; model WASM CI remains independent.

Every shared and static native install must also pass a clean external CMake
consumer build and executable test before its archive is accepted. The native
`dist` gate runs each source repository's original test suite from the static
build as part of the same invocation.

The MATLAB bundle is a zip holding the toolbox package
`OpenOcean-Field-Toolbox-<release-id>-win64.mltbx` beside
`examples/reference/cases/`, the 35-case benchmark library. The toolbox uses
UUID `openocean-field-tools`, supports Windows x64 and MATLAB
R2023a or later, and is tested with R2025b. Its runtime comes from the same
MSVC build as the release gates; MinGW DLLs are rejected. The toolbox carries
generated help pages, so `doc openocean` opens the guides and the API
reference from the installed copy.

Publication refuses an existing tag or Release. A successful publish creates
the configured `release.tag` (default `v{version}`) in this repository at the orchestrator commit recorded in the
lock, then creates the public Release and uploads only final products and
provenance files. Automatic notes list every locked source revision and, when
the runner still has the preceding published lock, link to each changed
repository's GitHub comparison. A successful publish marks the local sealed
state so the next release can select that lock as its comparison base.

Release IDs support `X.Y.Z` and the existing `YYYY.M.D.N` form. The 1.0.0
configuration uses the exact tag and title `OpenOcean-Field-V1.0.0`.

The wheel image can reuse the provisioned Eigen headers with
`tools/Dockerfile.wheel-eigen`. Its two base image digests are pinned; when
building offline with local tag overrides, verify those digests first. Record
the resulting immutable image digest in the private runner configuration.
