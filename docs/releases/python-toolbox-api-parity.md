# Python Toolbox API parity candidate

This updates the source pins for the next package build. It does **not** replace
assets in the published `OpenOcean-Field-V1.0.0` release or move that tag.

Validated sources:

| Component | Commit |
| --- | --- |
| FieldCore | `1a2d384f478b321d7311a32ee293e076ee5fb5ba` |
| Toolbox | `6a051ca3ea338f0b426ccca25f2b04428186ed1b` |

Other model source pins are unchanged. The Windows Python candidate reuses the
previously validated model wheels, rebuilds Core for each ABI, and rebuilds the
Toolbox facade. Core's native plugin ABI is unchanged.

The Python facade now provides model option groups, enum-based controls,
FieldCase JSON restoration, transmission-loss plotting, independent run
execution settings, and persistent `cwd/cache` output. It exports MATLAB-readable
numeric manifests, pressure SHD, and RayMode RAY/ARR products. The installer
reinstalls the bundle's exact wheels even when component version numbers match
an older installation. Wheel staging only copies declared package sources.

The common field remains `[frequency, source, bearing, depth, range]`.
FieldRunner's NormalMode numeric manifest now correctly describes the underlying
`[frequency, source, range, depth]` storage. Python names use snake_case and
indices start at zero. The Toolbox Python README records standalone-only
controls that the FieldCore facade cannot execute, including PE kernel-only
output and paired irregular RayMode receivers.

Validation on 2026-09-23:

- Windows CPython 3.10, 3.11, 3.12, 3.13 and 3.14: 14 Core tests and 40 Toolbox
  tests per ABI, using installed wheels and actual native calculations.
- Windows candidate ZIP: 31 wheel hashes and sizes checked; actual installer
  run against CPython 3.10 passed, including backend/API probes.
- Linux CPython 3.14: 14 Core tests and 40 installed-wheel Toolbox tests passed.
- Linux FieldRunner: 24 contract tests and typed six-model/file-output parity
  passed. MATLAB documentation tests: 6 passed.
- MATLAB R2025b: Python results from all ten pressure models and six RayMode
  ray/arrival cases read successfully; pressure samples, arrival offsets,
  amplitudes/delays and ray coordinates matched. A separate SHD fixture checked
  frequency, source x/y/depth, bearing, depth and range axes.
- Original Munk example: `(1, 1, 1, 501, 991)` pressure, SHD and TL figure produced.
- Release configuration/orchestrator: 25 tests passed.

Candidate filename: `OpenOcean-Field-Python-1.0.0-windows-x86_64.zip`.
SHA-256: `b1bb86c6d908f39d9d494b0d533115aa58b84ff0e8b9d2bb1e979bc6ba7abc93`.

The candidate has the requested 1.0.0 suite version for local evaluation. A full
release rebuild, including the remaining Linux ABIs and the updated Windows
FieldRunner/MATLAB runtime, is separate from this candidate validation. Existing
published release manifests remain the authoritative record for their assets.
