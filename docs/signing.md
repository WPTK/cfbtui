# Code signing cfbtui.exe

**Decision (October 2026): the Windows exe stays unsigned.** Revisit when a user reports that the SmartScreen
warning stops them, or when a free or cheap route below becomes a clear fit.

## What protects an update

The self-updater checks a download against the `SHA256SUMS` published with the same release. That protects against
a corrupted or truncated download. It does not protect against a compromised GitHub account: whoever can publish a
release can publish matching sums. Two things limit the damage: releases are immutable (a setting on the repository),
so a published release cannot be changed later, and every binary carries a build attestation anyone can check by hand
with `gh attestation verify cfbtui-linux-x86_64 -R WPTK/cfbtui`. An offline signing key was considered and rejected
as too much ceremony for this app; the attestation check stays manual.

## Why it matters

An unsigned exe downloaded from the internet triggers the Windows SmartScreen "Windows protected your PC" warning
(**More info**, then **Run anyway**). A signed exe shows a verified publisher, but signing does not clear the warning
at once: SmartScreen also judges reputation, which builds as many people download and run the file. Self-updates
download through the app itself, not a browser, so only the first manual download should meet the warning
(not tested).

## Options (prices and rules as of October 2026)

| Option | Yearly cost | SmartScreen effect | Fit |
|---|---|---|---|
| Azure Artifact Signing (was Trusted Signing) | about $120 ($9.99 a month) | Reputation builds over time; warnings continue at first | Individuals qualify in the USA and Canada only. No hardware token; works from Actions. Identity validation takes a few business days |
| OV certificate (DigiCert, Sectigo) | $150 to $300 | Same | Since June 2023 the private key must be on a hardware token or cloud HSM, so a plain `.pfx` in a secret is not offered. Needs the CA's cloud-signing add-on (price not checked) |
| EV certificate | $400 and up | Same as OV since 2024; the instant bypass is gone | Not worth it |
| SignPath Foundation (free for open source) | $0 | OV level; reputation still builds | Needs defined author, reviewer and approver roles, MFA, an approval click on every release, a published signing policy page, and a reputation check a new project may fail. The publisher shown is SignPath Foundation |
| Stay unsigned | $0 | Strong SmartScreen block | Today. The README documents the click-through and how to check a download |

Sources: [Microsoft: code signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options),
[SignPath terms](https://signpath.org/terms).

## What was removed

The repository used to carry a `.pfx`-based signing path (`scripts/sign_exe.ps1`, a "Sign the exe" step in
`release.yml`, a `-SkipSign` switch in `scripts/build_exe.ps1`). It never ran: no certificate was ever configured.
It is deleted so there is no dormant code path to maintain; restore it from git history (the commit that added
this note shows what went) if a certificate arrives. A cloud signing service would need a different step anyway.

## Checking a downloaded exe

Unsigned means `Get-AuthenticodeSignature` reports `NotSigned`. To check the download, use `SHA256SUMS` as the
README describes, or `gh attestation verify`.
