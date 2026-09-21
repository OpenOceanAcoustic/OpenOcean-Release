# Release runner environment

The interactive operator starts releases locally. A dedicated service account
owns Docker access, the self-hosted Actions runner, the Windows VM, and release
storage. The VM private key remains readable only by that service account.

Release output and caches live under one host root:

```text
<release-storage-root>/
├── linux/
├── win/
├── cache/
├── staging/
└── releases/
```

These are example paths. The actual values belong only in the uncommitted
runner YAML. Linux and Windows jobs write archives to the matching platform
directory. Release assembly always uses a release-specific directory and never
selects the newest file from a shared flat directory.

The Windows VM must use **Windows Server with Desktop Experience**. Server Core
does not contain the graphics components required by the MATLAB toolbox test
suite and cannot be converted in place. `preflight` checks the installation
type and runs an invisible `imagesc` smoke test before any release build.

The Windows build-tool virtual environment is intentionally outside `PATH`;
the private runner configuration points to it directly. It provides
`cibuildwheel 3.4.0`, so the build frontend cannot replace or shadow the
machine's default Python installation.

The persistent wheelhouse contains offline dependencies for CPython 3.10
through 3.14. Normal CI receives read-only access; administrators retain write
access. `main.py preflight` restores the fixed interpreter matrix and rebuilds
the complete wheelhouse when its completion marker is absent. The tool Python,
cibuildwheel cache, and wheelhouse paths come only from the private runner
configuration.

The manual Actions workflow requires the repository or organization secret
`OOA_FIELD_READ_TOKEN` for read-only access to the private source repositories.
It uses the workflow `GITHUB_TOKEN` only when the explicit `publish` operation
creates the tag and GitHub Release in this repository.

Inspect the VM using the controller and PowerShell runner paths from the private
runner YAML. For example:

```bash
sudo -u <service-account> -H python3 <vm-controller> status
printf 'whoami\n' | sudo -u <service-account> -H <powershell-runner>
```

The host Windows directory is a durable mirror. Sources and products cross the
private SSH channel configured by `ssh_host`, `ssh_port`, `ssh_private_key`,
and `ssh_known_hosts`; the VM therefore does not depend on a permanently mapped
network drive. The guest staging root is cleaned per release ID. Proxy settings
remain host/VM configuration and are redacted from logs.
