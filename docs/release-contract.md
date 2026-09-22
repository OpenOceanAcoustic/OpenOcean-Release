# Release contract

The supported sources are FieldCore, RayMode, NormalMode, PE, and Toolbox.
WI and Couple are reserved configuration entries and fail validation when
enabled until release adapters exist.

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

The full profile produces four native packages for each of Linux and Windows,
one Python SDK bundle for each OS, and one Windows MATLAB bundle. Native
packages contain shared, static, executable, headers, licenses, dependency
notes, and CMake metadata. Each Python bundle contains a pure facade wheel plus
FieldCore, Bellhop, NormalMode, and PE native wheels for CPython 3.10 through
3.14, with an ABI-selecting `install.py`. FieldRunner is built and tested as an
internal runtime and has no separate customer asset. WASM, WI, and Couple are
not published.

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
`v<release-id>` in this repository at the orchestrator commit recorded in the
lock, then creates the public Release and uploads only final products and
provenance files. Automatic notes list every locked source revision and, when
the runner still has the preceding published lock, link to each changed
repository's GitHub comparison. A successful publish marks the local sealed
state so the next release can select that lock as its comparison base.
