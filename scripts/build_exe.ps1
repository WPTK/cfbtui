# Build dist\cfbtui.exe and dist\cfbtui.exe.sha256. Run from the repo root.
$ErrorActionPreference = "Stop"
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $py scripts\version_info.py
& $py -m PyInstaller --noconfirm --clean --workpath .pyi-build cfbtui.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$hash = (Get-FileHash dist\cfbtui.exe -Algorithm SHA256).Hash.ToLower()
"$hash  cfbtui.exe" | Set-Content -Encoding ascii dist\cfbtui.exe.sha256
Write-Host "dist\cfbtui.exe  sha256 $hash"
