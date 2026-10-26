# Build dist\cfbtui.exe and dist\cfbtui.exe.sha256. Run from the repo root. The exe is not code-signed (docs/signing.md).
$ErrorActionPreference = "Stop"
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

& $py scriptsersion_info.py
if ($LASTEXITCODE -ne 0) { throw "could not write the version resource" }
& $py -m PyInstaller --noconfirm --clean --workpath .pyi-build cfbtui.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

& "$PSScriptRoot\hash_exe.ps1"
