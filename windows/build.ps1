[CmdletBinding()]
param(
    [switch]$SkipBootstrap,
    [switch]$BuildInstaller
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $PSScriptRoot ".venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $Python)) {
    python -m venv $VenvDir
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to update pip."
}
& $Python -m pip install -r (Join-Path $PSScriptRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Windows build dependencies."
}

if (-not $SkipBootstrap) {
    & (Join-Path $PSScriptRoot "bootstrap-dependencies.ps1")
}

if (-not (Test-Path (Join-Path $PSScriptRoot "runtime\java\bin\java.exe"))) {
    throw "Bundled Java is missing. Run bootstrap-dependencies.ps1 first."
}
if (-not (Test-Path (Join-Path $PSScriptRoot "runtime\java\bin\keytool.exe"))) {
    throw "Bundled keytool is missing. Run bootstrap-dependencies.ps1 first."
}
if (-not (Test-Path (Join-Path $PSScriptRoot "runtime\platform-tools\adb.exe"))) {
    throw "Bundled ADB is missing. Run bootstrap-dependencies.ps1 first."
}

Push-Location $ProjectDir
try {
    & $Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) {
        throw "The test suite failed."
    }
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "quest-apk-renamer.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }

    if ($BuildInstaller) {
        $IsccCandidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )
        $Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $Iscc) {
            throw "Inno Setup 6 was not found. Install it or omit -BuildInstaller."
        }
        & $Iscc (Join-Path $PSScriptRoot "installer.iss")
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup failed."
        }
    }
}
finally {
    Pop-Location
}

Write-Host "Windows build complete: $ProjectDir\dist"
