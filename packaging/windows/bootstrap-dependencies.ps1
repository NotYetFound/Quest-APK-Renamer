[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RuntimeDir = Join-Path $PSScriptRoot "runtime"
$Lock = Get-Content (Join-Path $ProjectDir "packaging\runtime-lock.json") -Raw | ConvertFrom-Json
$JavaArtifact = $Lock.temurin.'windows-x86_64'
$PlatformArtifact = $Lock.platform_tools.'windows-x86_64'
$JavaDir = Join-Path $RuntimeDir "java"
$PlatformToolsDir = Join-Path $RuntimeDir "platform-tools"
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$TempDir = Join-Path ([IO.Path]::GetTempPath()) ("qar-windows-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $RuntimeDir, $TempDir | Out-Null

try {
    & $Python (Join-Path $ProjectDir "scripts\fetch_pinned_tools.py") $RuntimeDir --project $ProjectDir
    if ($LASTEXITCODE -ne 0) { throw "Pinned Android component download failed." }
    $HashFile = Join-Path $RuntimeDir "DEPENDENCY-HASHES.txt"
    if ($Force -or -not (Test-Path (Join-Path $JavaDir "bin\java.exe"))) {
        $Archive = Join-Path $TempDir "temurin.zip"
        $Extract = Join-Path $TempDir "temurin"
        $Linked = Join-Path $TempDir "java"
        $Url = $JavaArtifact.url
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Archive
        $ActualHash = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -ne $JavaArtifact.sha256) {
            throw "Temurin SHA-256 mismatch; refusing to use the download."
        }
        Expand-Archive $Archive $Extract
        $Jdk = Get-ChildItem $Extract -Directory | Select-Object -First 1
        if (-not $Jdk) { throw "Temurin did not contain a JDK." }
        & (Join-Path $Jdk.FullName "bin\jlink.exe") `
            --add-modules "java.base,java.desktop,java.logging" `
            --strip-debug --no-header-files --no-man-pages --compress=2 --output $Linked
        if ($LASTEXITCODE -ne 0) { throw "jlink failed." }
        if (Test-Path $JavaDir) { Remove-Item -LiteralPath $JavaDir -Recurse -Force }
        Move-Item $Linked $JavaDir
    }
    if ($Force -or -not (Test-Path (Join-Path $PlatformToolsDir "adb.exe"))) {
        $Archive = Join-Path $TempDir "platform-tools.zip"
        $Extract = Join-Path $TempDir "android"
        $Url = $PlatformArtifact.url
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Archive
        $ActualHash = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualHash -ne $PlatformArtifact.sha256) {
            throw "Platform Tools SHA-256 mismatch; refusing to use the download."
        }
        Expand-Archive $Archive $Extract
        $Found = Join-Path $Extract "platform-tools"
        if (-not (Test-Path (Join-Path $Found "adb.exe"))) { throw "ADB was not found." }
        if (Test-Path $PlatformToolsDir) { Remove-Item -LiteralPath $PlatformToolsDir -Recurse -Force }
        Move-Item $Found $PlatformToolsDir
    }
    @(
        "Temurin version: $($JavaArtifact.version)"
        "Temurin archive SHA256: $($JavaArtifact.sha256)"
        "Temurin source: $($JavaArtifact.url)"
        "Platform-Tools version: $($PlatformArtifact.version)"
        "Platform-Tools archive SHA256: $($PlatformArtifact.sha256)"
        "Platform-Tools source: $($PlatformArtifact.url)"
    ) | Set-Content -Encoding UTF8 $HashFile
    & (Join-Path $JavaDir "bin\java.exe") -jar (Join-Path $RuntimeDir "tools\apktool.jar") --version
    if ($LASTEXITCODE -ne 0) { throw "Apktool runtime check failed." }
    & (Join-Path $JavaDir "bin\java.exe") -jar (Join-Path $RuntimeDir "tools\uber-apk-signer.jar") --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Signer runtime check failed." }
    & (Join-Path $PlatformToolsDir "adb.exe") version
}
finally {
    if (Test-Path $TempDir) { Remove-Item -LiteralPath $TempDir -Recurse -Force }
}
