# Build dist\cfbtui.exe and dist\cfbtui.exe.sha256. Run from the repo root.
#   scripts\build_exe.ps1            build, sign if SIGN_CERT_BASE64 is set, hash
#   scripts\build_exe.ps1 -SkipSign  build and hash only (CI signs in its own step, between build and hash)
param([switch]$SkipSign)
$ErrorActionPreference = "Stop"
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

& $py scripts\version_info.py
if ($LASTEXITCODE -ne 0) { throw "could not write the version resource" }
& $py -m PyInstaller --noconfirm --clean --workpath .pyi-build cfbtui.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

if (-not $SkipSign) { & "$PSScriptRoot\sign_exe.ps1" }
& "$PSScriptRoot\hash_exe.ps1"
