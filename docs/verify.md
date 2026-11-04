# Verify a download

Each release has a `SHA256SUMS` file. Save it next to your download, then run the command for your system.

Linux:

```sh
sha256sum -c --ignore-missing SHA256SUMS
```

macOS:

```sh
shasum -a 256 -c --ignore-missing SHA256SUMS
```

Windows PowerShell: run the command below and compare the output with the matching line in `SHA256SUMS`.

```powershell
(Get-FileHash .\cfbtui-windows-x86_64.exe).Hash
```

`SHA256SUMS` catches a corrupted download. It does not protect against a compromised GitHub account.

## Build attestations

The binaries, tarball and wheel carry GitHub build attestations. With the [GitHub CLI](https://cli.github.com/) installed, run:

```sh
gh attestation verify cfbtui-linux-x86_64 -R WPTK/cfbtui
```

The Windows exe is not code-signed, so `Get-AuthenticodeSignature` reports `NotSigned`. See [signing.md](signing.md) for why.
