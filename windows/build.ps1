param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OutputDirectory = Join-Path $PSScriptRoot "out"
$WorkDirectory = Join-Path $PSScriptRoot "build"

Set-Location $ProjectRoot
if (-not $SkipTests) {
    python tools/run_tests.py shared
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
}

python -m pip install -e ".[windows-build]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $WorkDirectory | Out-Null

foreach ($Spec in @("LockLockAgent.spec", "LockLockCli.spec", "LockLockService.spec")) {
    python -m PyInstaller --noconfirm --clean `
        --distpath $OutputDirectory --workpath $WorkDirectory `
        (Join-Path $PSScriptRoot $Spec)
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for $Spec" }
}

Copy-Item (Join-Path $PSScriptRoot "common.ps1") $OutputDirectory -Force
Copy-Item (Join-Path $PSScriptRoot "install.ps1") $OutputDirectory -Force
Copy-Item (Join-Path $PSScriptRoot "uninstall.ps1") $OutputDirectory -Force
Copy-Item (Join-Path $PSScriptRoot "test-hardware.ps1") $OutputDirectory -Force
Copy-Item (Join-Path $PSScriptRoot "README.md") $OutputDirectory -Force

Write-Host "Unsigned Windows bundle created at $OutputDirectory"
Write-Host "Code-sign the three EXE files and installer scripts before distribution."
