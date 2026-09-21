# OpenOcean Field Release

This public repository is the single build and publication entry point for the
OpenOcean Field product family. A build resolves every source ref to a commit,
runs the complete selected platform and ABI matrix, and seals immutable local
artifacts. Publication is a separate explicit operation.

```bash
export OPENOCEAN_RUNNER_CONFIG="$HOME/.config/openocean/runner.yaml"
export OOA_FIELD_READ_TOKEN=...

# build, test, package, and seal locally; nothing is uploaded
python main.py -c release.yaml
python main.py build -c release.yaml

# inspect all runner prerequisites without building
python main.py preflight -c release.yaml

# resume or selectively rebuild a checksum-tracked task
python main.py build -c release.yaml --resume 2026.9.20.1
python main.py build -c release.yaml --resume 2026.9.20.1 \
  --rebuild windows.python

# the only operation that creates a tag and public GitHub Release
export GH_TOKEN=...
python main.py publish --release-id 2026.9.20.1
```

`publish` reads the normalized configuration, source lock, task state,
manifest, checksums, and test summary from the sealed release ID. It accepts no
new build choices. Supplying `-c release.yaml` is optional and only verifies
that the file matches the sealed configuration.

`release.yaml` is public and portable. Host paths, VM controls, caches, proxy
details, and credential variable names live in an uncommitted runner file based
on [`runner.example.yaml`](runner.example.yaml). See
[`docs/runner-environment.md`](docs/runner-environment.md) for provisioning and
[`docs/release-contract.md`](docs/release-contract.md) for assets and gates.

Only `workflow_dispatch` is defined. Pull requests, pushes, and tags never
build or publish a release, and the workflow uploads no Actions artifacts.
