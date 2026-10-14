# Signing cfbtui.exe

## Why

An unsigned exe downloaded from the internet triggers the Windows SmartScreen "Windows protected your PC" warning. Signing the exe with a code signing certificate attaches a verified publisher name, which is the first step toward that warning going away.

Signing alone does not clear it instantly. SmartScreen also judges reputation, and reputation builds as many people download and run the signed file. Expect warnings to continue for a while after the first signed release.

## Options (check current pricing and requirements for each)

- **Azure Artifact Signing (formerly Trusted Signing).** Microsoft's cloud service. No hardware token, works from CI. Requires an Azure account and identity validation, and eligibility depends on your country and whether you are an individual or an organization. It signs through its own tool and not a .pfx file, so see the note at the end.
- **Standard (OV) certificate from a certificate authority.** Cheaper than EV. Current CA rules generally require the private key to live on a hardware token or in a cloud HSM, so a plain downloadable .pfx may not be offered. Ask the CA before buying whether you can get a .pfx or a CI-friendly signing method.
- **EV certificate.** Gives instant SmartScreen reputation but costs more and ships on a hardware token, which does not work in GitHub Actions runners.
- **Nothing.** Users click "More info" then "Run anyway". The `SHA256SUMS` file on each release lets careful users verify the download.

## Add the secrets (once you have a .pfx)

1. Encode the certificate and copy it to the clipboard (PowerShell, in the folder holding the file):

   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx")) | Set-Clipboard
   ```

2. In GitHub: repo WPTK/cfbtui, Settings, Secrets and variables, Actions, New repository secret.
3. Create `SIGN_CERT_BASE64` and paste the clipboard.
4. Create `SIGN_CERT_PASSWORD` with the .pfx password.

Until both exist, the build prints "Not signing: SIGN_CERT_BASE64 is not set." and carries on as before. The next tagged release signs the exe automatically, and the `SHA256SUMS` entry is computed from the signed file.

## Test locally

Needs the Windows SDK (for signtool.exe). From the repo root:

```powershell
$env:SIGN_CERT_BASE64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\path\cert.pfx"))
$env:SIGN_CERT_PASSWORD = "the password"
powershell -File scripts\build_exe.ps1
Remove-Item Env:SIGN_CERT_BASE64, Env:SIGN_CERT_PASSWORD
```

The script signs, runs `signtool verify /pa`, and deletes its temp copy of the .pfx.

## Check a downloaded exe

```powershell
Get-AuthenticodeSignature .\cfbtui.exe | Select-Object Status, SignerCertificate
```

`Status` should be `Valid`. `NotSigned` means no signature. The release workflow also prints this after each build.

## If the service does not use a .pfx

Azure Artifact Signing and some CA cloud services sign through their own tool or action. The block marked "Code signing" in `scripts/build_exe.ps1` is the only thing to change: replace the signtool call, keep it before the SHA-256 line, and update the secrets in `.github/workflows/release.yml` to match.
