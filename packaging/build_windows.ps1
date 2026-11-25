param([string]$AniListClientId = "", [switch]$OfflineCandidate)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw 'Use Windows x64 to build this package.' }
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Build command failed ($LASTEXITCODE)." } }
py -3.12 -c "import struct; import platform; assert struct.calcsize('P') == 8 and platform.machine().lower() in ('amd64','x86_64'), 'x64 Python required'"
Check-Exit
py -3.12 -m venv .build-venv
Check-Exit
$python = Join-Path $PWD '.build-venv\Scripts\python.exe'
& $python -m pip install -r requirements.txt 'pyinstaller==6.16.0'
Check-Exit
# Clean only generated build directories. User AppData is never an input.
if (Test-Path build\clean-source) { Remove-Item build\clean-source -Recurse -Force }
if (Test-Path dist\AniVault) { Remove-Item dist\AniVault -Recurse -Force }
if ($OfflineCandidate) { & $python packaging\stage_release.py build\clean-source --offline-candidate }
elseif ($AniListClientId) { & $python packaging\stage_release.py build\clean-source $AniListClientId }
else { & $python packaging\stage_release.py build\clean-source }
Check-Exit
# Keep unrelated toolchain DLLs (for example Poppler's ICU) out of dependency discovery.
$buildSearchPath = $env:PATH
try {
    $env:PATH = ((Split-Path $python), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
    & $python -m PyInstaller --noconfirm --clean packaging\AniVault.spec
    Check-Exit
} finally { $env:PATH = $buildSearchPath }
$tls = Start-Process -FilePath (Join-Path $PWD "dist\AniVault\AniVault.exe") -ArgumentList "--check-tls" -WindowStyle Hidden -Wait -PassThru
if ($tls.ExitCode -ne 0) { throw "Packaged HTTPS initialization failed." }
& $python packaging\audit_bundle.py dist\AniVault
Check-Exit
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw 'Install Inno Setup 6 and rerun to compile the installer.' }
& $iscc packaging\AniVault.iss
Check-Exit
Get-FileHash dist\installer\AniVault-1.9.0-Setup.exe -Algorithm SHA256
Write-Host 'Built Windows installer. Follow the release-specific verification notes before publishing.'
