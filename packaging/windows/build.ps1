[CmdletBinding()]
param([switch]$SkipBootstrap, [switch]$BuildInstaller)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$VenvDir = Join-Path $PSScriptRoot ".venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $Python)) { python -m venv $VenvDir }
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $ProjectDir "packaging\requirements-build.txt") -e $ProjectDir
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed." }
if (-not $SkipBootstrap) {
    $env:PYTHON_BIN = $Python
    & (Join-Path $PSScriptRoot "bootstrap-dependencies.ps1")
}
$RuntimeDir = Join-Path $PSScriptRoot "runtime"
$RequiredRuntimeFiles = @(
    "java\bin\java.exe",
    "java\bin\keytool.exe",
    "platform-tools\adb.exe",
    "tools\apktool.jar",
    "tools\uber-apk-signer.jar",
    "tools\libovrplatformloader.so"
)
foreach ($RelativePath in $RequiredRuntimeFiles) {
    $RequiredPath = Join-Path $RuntimeDir $RelativePath
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Bundled runtime is incomplete: missing $RequiredPath"
    }
}
$AppVersion = (& $Python -c "from quest_renamer import __version__; print(__version__)").Trim()
$Generated = Join-Path $PSScriptRoot "generated"
& $Python (Join-Path $ProjectDir "scripts\render_release_icons.py") $Generated --project $ProjectDir
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed." }

$Parts = @($AppVersion.Split('.'))
while ($Parts.Count -lt 4) { $Parts += "0" }
$NumericVersion = ($Parts[0..3] -join ',')
$VersionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($NumericVersion), prodvers=($NumericVersion), mask=0x3f,
    flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable(u'040904B0', [
    StringStruct(u'CompanyName', u'Quest APK Renamer'),
    StringStruct(u'FileDescription', u'Quest APK Renamer'),
    StringStruct(u'FileVersion', u'$AppVersion'),
    StringStruct(u'InternalName', u'Quest APK Renamer'),
    StringStruct(u'LegalCopyright', u'Copyright (c) 2026 RockoTheeHut'),
    StringStruct(u'OriginalFilename', u'Quest APK Renamer.exe'),
    StringStruct(u'ProductName', u'Quest APK Renamer'),
    StringStruct(u'ProductVersion', u'$AppVersion')
  ])]), VarFileInfo([VarStruct(u'Translation', [1033, 1200])])]
)
"@
$VersionFile = Join-Path $Generated "version-info.txt"
$VersionInfo | Set-Content -Encoding UTF8 $VersionFile

Push-Location $ProjectDir
try {
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
    $env:QAR_PACKAGE_RUNTIME = $RuntimeDir
    $env:QAR_PACKAGE_ICON = Join-Path $Generated "app-icon.ico"
    $env:QAR_WINDOWS_VERSION_FILE = $VersionFile
    $env:APP_VERSION = $AppVersion
    & $Python -m PyInstaller --noconfirm --clean "packaging\quest-apk-renamer.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
    $App = Join-Path $ProjectDir "dist\Quest APK Renamer\Quest APK Renamer.exe"
    & $App --smoke-test
    if ($LASTEXITCODE -ne 0) { throw "Packaged app smoke test failed." }
    $Zip = Join-Path $ProjectDir "dist\Quest-APK-Renamer-$AppVersion-Windows-portable.zip"
    Compress-Archive -Path (Join-Path $ProjectDir "dist\Quest APK Renamer\*") -DestinationPath $Zip -Force
    (Get-FileHash $Zip -Algorithm SHA256).Hash + "  " + (Split-Path -Leaf $Zip) |
        Set-Content -Encoding ASCII "$Zip.sha256"
    if ($BuildInstaller) {
        $Iscc = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $Iscc) { throw "Install Inno Setup 6 or omit -BuildInstaller." }
        & $Iscc "/DMyAppVersion=$AppVersion" (Join-Path $PSScriptRoot "installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }
        $Installer = Get-ChildItem (Join-Path $ProjectDir "dist\installer\*.exe") |
            Select-Object -First 1
        if (-not $Installer) { throw "The installer output was not found." }
        (Get-FileHash $Installer.FullName -Algorithm SHA256).Hash + "  " + $Installer.Name |
            Set-Content -Encoding ASCII ($Installer.FullName + ".sha256")
    }
}
finally { Pop-Location }
