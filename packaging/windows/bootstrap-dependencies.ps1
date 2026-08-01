[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$RuntimeDir = Join-Path $PSScriptRoot "runtime"
$JavaDir = Join-Path $RuntimeDir "java"
$PlatformToolsDir = Join-Path $RuntimeDir "platform-tools"
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$TempDir = Join-Path ([IO.Path]::GetTempPath()) ("qar-windows-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $RuntimeDir, $TempDir | Out-Null

try {
    & $Python (Join-Path $ProjectDir "scripts\fetch_pinned_tools.py") $RuntimeDir --project $ProjectDir
    if ($LASTEXITCODE -ne 0) { throw "Pinned Android component download failed." }
    $HashFile = Join-Path $RuntimeDir "DEPENDENCY-HASHES.txt"
    $HashLines = if (Test-Path -LiteralPath $HashFile) { @(Get-Content $HashFile) } else { @() }
    if ($Force -or -not (Test-Path (Join-Path $JavaDir "bin\java.exe"))) {
        $Archive = Join-Path $TempDir "temurin.zip"
        $Extract = Join-Path $TempDir "temurin"
        $Linked = Join-Path $TempDir "java"
        $Url = "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Archive
        Expand-Archive $Archive $Extract
        $Jdk = Get-ChildItem $Extract -Directory | Select-Object -First 1
        if (-not $Jdk) { throw "Temurin did not contain a JDK." }
        & (Join-Path $Jdk.FullName "bin\jlink.exe") `
            --add-modules "java.base,java.desktop,java.logging" `
            --strip-debug --no-header-files --no-man-pages --compress=2 --output $Linked
        if ($LASTEXITCODE -ne 0) { throw "jlink failed." }
        if (Test-Path $JavaDir) { Remove-Item -LiteralPath $JavaDir -Recurse -Force }
        Move-Item $Linked $JavaDir
        $HashLines += "Temurin archive SHA256: $((Get-FileHash $Archive -Algorithm SHA256).Hash)"
        $HashLines += "Temurin source: $Url"
    }
    if ($Force -or -not (Test-Path (Join-Path $PlatformToolsDir "adb.exe"))) {
        $Archive = Join-Path $TempDir "platform-tools.zip"
        $Extract = Join-Path $TempDir "android"
        $Url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Archive
        Expand-Archive $Archive $Extract
        $Found = Join-Path $Extract "platform-tools"
        if (-not (Test-Path (Join-Path $Found "adb.exe"))) { throw "ADB was not found." }
        if (Test-Path $PlatformToolsDir) { Remove-Item -LiteralPath $PlatformToolsDir -Recurse -Force }
        Move-Item $Found $PlatformToolsDir
        $HashLines += "Platform-Tools archive SHA256: $((Get-FileHash $Archive -Algorithm SHA256).Hash)"
        $HashLines += "Platform-Tools source: $Url"
    }
    if ($HashLines.Count -gt 0) { $HashLines | Set-Content -Encoding UTF8 $HashFile }
    & (Join-Path $JavaDir "bin\java.exe") -jar (Join-Path $RuntimeDir "tools\apktool.jar") --version
    if ($LASTEXITCODE -ne 0) { throw "Apktool runtime check failed." }
    & (Join-Path $JavaDir "bin\java.exe") -jar (Join-Path $RuntimeDir "tools\uber-apk-signer.jar") --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Signer runtime check failed." }
    & (Join-Path $PlatformToolsDir "adb.exe") version
}
finally {
    if (Test-Path $TempDir) { Remove-Item -LiteralPath $TempDir -Recurse -Force }
}
