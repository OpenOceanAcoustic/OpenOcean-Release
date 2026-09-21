#Requires -Version 5.1
#Requires -RunAsAdministrator

param(
    [Parameter(Mandatory = $true)][string] $ToolPython,
    [Parameter(Mandatory = $true)][string] $Wheelhouse,
    [Parameter(Mandatory = $true)][string] $CibuildwheelCache,
    [switch] $KeepProxy
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (@(Get-Process Runner.Worker -ErrorAction SilentlyContinue).Count -ne 0) {
    throw "The Windows Actions runner is busy. Provision the wheelhouse while it is idle."
}
if (-not (Test-Path -LiteralPath $ToolPython)) {
    throw "Missing isolated cibuildwheel Python: $ToolPython"
}

$cibuildwheelVersion = & $ToolPython -c `
    "import importlib.metadata; print(importlib.metadata.version('cibuildwheel'))"
if ($LASTEXITCODE -ne 0 -or $cibuildwheelVersion -ne "3.4.0") {
    throw "Expected cibuildwheel 3.4.0 in $ToolPython; found '$cibuildwheelVersion'"
}

$proxyNames = @(
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy"
)
$savedProxy = @{}
foreach ($name in $proxyNames) {
    $savedProxy[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    if (-not $KeepProxy) {
        foreach ($name in @("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        }
        $env:NO_PROXY = "*"
        $env:no_proxy = "*"
    }

    New-Item -ItemType Directory -Force -Path $CibuildwheelCache | Out-Null
    $env:CIBW_CACHE_PATH = $CibuildwheelCache
    $provisionPython = @'
from cibuildwheel.platforms.windows import all_python_configurations, install_cpython

wanted = {
    "cp310-win_amd64",
    "cp311-win_amd64",
    "cp312-win_amd64",
    "cp313-win_amd64",
    "cp314-win_amd64",
}
configurations = {item.identifier: item for item in all_python_configurations()}
missing = sorted(wanted - configurations.keys())
if missing:
    raise SystemExit(f"missing cibuildwheel configurations: {missing}")
for identifier in sorted(wanted):
    path = install_cpython(configurations[identifier])
    print(f"READY {identifier} {path}", flush=True)
'@
    # Windows PowerShell 5 rewrites quotes in multiline native-command
    # arguments.  Execute a UTF-8 script file so Python receives the source
    # byte-for-byte (in particular the f-string quotes above).
    $provisionFile = Join-Path $env:TEMP "openocean-provision-cpython.py"
    try {
        [IO.File]::WriteAllText(
            $provisionFile,
            $provisionPython,
            [Text.UTF8Encoding]::new($false)
        )
        & $ToolPython $provisionFile
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to provision the cibuildwheel CPython toolchains"
        }
    }
    finally {
        Remove-Item -LiteralPath $provisionFile -Force -ErrorAction SilentlyContinue
    }

    $hostRequirements = @(
        "cibuildwheel==3.4.0",
        "matplotlib>=3.7",
        "mypy==1.17.1",
        "numpy>=1.23",
        "pybind11==3.1.0",
        "pybind11-stubgen==2.5.5",
        "pydantic>=2",
        "typing-extensions>=4.12",
        "wheel>=0.45"
    )
    $targetRequirements = @(
        "build==1.3.0",
        "cmake>=3.21",
        "delvewheel==1.11.2",
        "matplotlib>=3.7",
        "mypy==1.17.1",
        "ninja>=1.11",
        "numpy>=1.23",
        "pybind11==3.0.1",
        "pybind11-stubgen==2.5.5",
        "pydantic>=2",
        "scikit-build-core==0.11.6",
        "setuptools>=77",
        "typing-extensions>=4.12",
        "wheel>=0.45"
    )

    function Invoke-PipDownload {
        param(
            [Parameter(Mandatory = $true)] [string] $Python,
            [Parameter(Mandatory = $true)] [string[]] $Requirements
        )
        $arguments = @(
            "-m", "pip", "download",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--only-binary=:all:",
            "--retries", "10",
            "--timeout", "120",
            "--dest", $Wheelhouse
        ) + $Requirements
        & $Python @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "pip download failed for $Python"
        }
    }

    function Test-OfflineRequirements {
        param(
            [Parameter(Mandatory = $true)] [string] $Python,
            [Parameter(Mandatory = $true)] [string[]] $Requirements
        )
        $arguments = @(
            "-m", "pip", "install",
            "--dry-run",
            "--ignore-installed",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-index",
            "--find-links", $Wheelhouse,
            "--quiet"
        ) + $Requirements
        & $Python @arguments | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "offline wheelhouse verification failed for $Python"
        }
    }

    New-Item -ItemType Directory -Force -Path $Wheelhouse | Out-Null
    Get-ChildItem -LiteralPath $Wheelhouse -Force -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force

    $hostPython = (Get-Command python.exe -ErrorAction Stop).Source
    Invoke-PipDownload -Python $hostPython -Requirements $hostRequirements

    $nugetRoot = Join-Path $CibuildwheelCache "nuget-cpython"
    $targetPythons = @(
        Get-ChildItem -LiteralPath $nugetRoot -Directory |
            Where-Object { $_.Name -match '^python\.3\.(10|11|12|13|14)\.' } |
            Sort-Object Name |
            ForEach-Object { Join-Path $_.FullName "tools\python.exe" } |
            Where-Object { Test-Path -LiteralPath $_ }
    )
    if ($targetPythons.Count -ne 5) {
        throw "Expected five CPython toolchains; found $($targetPythons.Count)"
    }
    foreach ($python in $targetPythons) {
        Invoke-PipDownload -Python $python -Requirements $targetRequirements
    }

    $markerContents = @(
        "schema=openocean.windows-wheelhouse/v2",
        "created=$([DateTime]::UtcNow.ToString('o'))",
        "python=3.10,3.11,3.12,3.13,3.14"
    )
    $markerContents | Set-Content -Encoding ascii `
        (Join-Path $Wheelhouse "openocean-v2.complete")
    # Model-repository dist CI consumes the same verified superset using its
    # established v1 marker name.
    $markerContents | Set-Content -Encoding ascii `
        (Join-Path $Wheelhouse "openocean-v1.complete")

    Test-OfflineRequirements -Python $hostPython -Requirements $hostRequirements
    foreach ($python in $targetPythons) {
        Test-OfflineRequirements -Python $python -Requirements $targetRequirements
    }

    $aclArguments = @(
        $Wheelhouse,
        "/inheritance:r",
        "/grant:r",
        "*S-1-5-32-544:(OI)(CI)F",
        "*S-1-5-18:(OI)(CI)F",
        "*S-1-5-20:(OI)(CI)RX"
    )
    & icacls.exe @aclArguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to protect the wheelhouse ACL"
    }

    $files = @(Get-ChildItem -LiteralPath $Wheelhouse -File)
    $bytes = ($files | Measure-Object Length -Sum).Sum
    Write-Host "Windows wheelhouse ready: $($files.Count) files, $bytes bytes"
}
finally {
    foreach ($name in $proxyNames) {
        [Environment]::SetEnvironmentVariable($name, $savedProxy[$name], "Process")
    }
}
