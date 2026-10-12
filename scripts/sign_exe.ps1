# Sign dist\cfbtui.exe when SIGN_CERT_BASE64 (a base64 .pfx) and SIGN_CERT_PASSWORD are set; otherwise do nothing.
# Kept apart from the build so the signing secrets are never in the environment of PyInstaller or its dependencies.
$ErrorActionPreference = "Stop"
if (-not $env:SIGN_CERT_BASE64) {
    Write-Host "Not signing: SIGN_CERT_BASE64 is not set."
    return
}
if (-not $env:SIGN_CERT_PASSWORD) { throw "SIGN_CERT_PASSWORD is not set" }

$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
    Sort-Object { [version]$_.Directory.Parent.Name } | Select-Object -Last 1
if (-not $signtool) { throw "signtool.exe not found under Windows Kits\10\bin; install the Windows SDK" }

$pfx = Join-Path ([IO.Path]::GetTempPath()) ("cfbtui-sign-" + [guid]::NewGuid().ToString("N") + ".pfx")
try {
    [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:SIGN_CERT_BASE64))
    $signed = $false
    foreach ($tsa in "http://timestamp.digicert.com", "http://timestamp.sectigo.com") {
        for ($try = 1; $try -le 2 -and -not $signed; $try++) {
            & $signtool.FullName sign /fd SHA256 /tr $tsa /td SHA256 /f $pfx /p $env:SIGN_CERT_PASSWORD dist\cfbtui.exe
            $signed = $LASTEXITCODE -eq 0
        }
        if ($signed) { break }
    }
    if (-not $signed) { throw "signtool sign failed" }
    & $signtool.FullName verify /pa dist\cfbtui.exe
    if ($LASTEXITCODE -ne 0) { throw "signtool verify failed" }
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}
