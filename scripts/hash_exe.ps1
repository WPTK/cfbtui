# Write dist\cfbtui.exe.sha256 for the exe as it is now.
$ErrorActionPreference = "Stop"
$hash = (Get-FileHash dist\cfbtui.exe -Algorithm SHA256).Hash.ToLower()
"$hash  cfbtui.exe" | Set-Content -Encoding ascii dist\cfbtui.exe.sha256
Write-Host "dist\cfbtui.exe  sha256 $hash"
