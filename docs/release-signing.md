# Signing releases

For the owner. The self-updater installs a new binary only if the release's `SHA256SUMS` carries a valid Ed25519
signature (`SHA256SUMS.sig`) from a key built into the app. The private key lives offline with you and never on
GitHub, so someone who can only publish or edit a GitHub release (a stolen token) cannot make an installed cfbtui
accept their file, provided you follow step 2 below before signing. A compromised workflow can still build a bad
binary; the attestation check in step 2 is what you rely on to notice, and it is no defence against a malicious change
merged to `main` and tagged. Releases up to 1.5.0 do not check anything; the protection starts with the first
release that carries the verification and covers updates from that version on.

`release.yml` stops at a draft release. You sign and publish by hand, about two minutes per release.

## Formats

- **Signature file** `SHA256SUMS.sig`: the raw 64-byte Ed25519 signature, base64 encoded, one line. Signed over the
  exact bytes of `SHA256SUMS`. Chosen because it is easy to produce, inspect and parse with the standard library; it is not
  minisign's format, so minisign cannot verify it.
- **Public keys** in `cfbtui/sigverify.py`: two, base64 of 32 bytes. `KEY_CURRENT` signs releases. `KEY_SPARE` is
  generated at the same time, kept apart and never used until the current key is lost or leaked.
- **Private key file**: one line of base64, the 32-byte seed. Whoever holds it can sign releases.

## One-time setup (you do this, once)

Do it on a machine you trust, outside any git checkout (`keygen` refuses to write inside one) and never in a shared
folder, cloud-synced folder or chat.

```sh
python scripts/sign_sums.py keygen /path/to/offline/cfbtui-signing.key
python scripts/sign_sums.py keygen /path/to/offline/cfbtui-spare.key
```

Each command writes a private seed (owner-only permissions on systems that have them, never overwrites a file; on Windows keep it in a
folder only you can read) and prints `public key: ...`. Put the first
public key in `KEY_CURRENT` and the second in `KEY_SPARE` in `cfbtui/sigverify.py` and commit that change like any
other. Until both are filled in, `release.yml` fails its first job and a build trusts no manifest (the updater
refuses every update), so an unfinished setup cannot ship by accident.

Where to keep the private keys:

- Each seed goes on storage that is offline and encrypted: a USB stick or an encrypted container (BitLocker To Go,
  VeraCrypt, `age`-encrypted file) with a strong passphrase. The seed file itself is not encrypted; the container is.
- Keep a second copy of each on a different stick in a different place. A lost key with no copy is a rotation event.
- Keep the spare apart from the signing key (a different stick, ideally a different place), because its whole
  value is surviving the loss of the other.
- Never put either in a repository, an Actions secret, a password-manager note synced to a browser, or an email.
- Record the public keys somewhere other than the repo too, so you can tell if `sigverify.py` was altered.

## Each release (about two minutes)

1. Tag and push as usual ([development.md](development.md)). The workflow tests, runs the updater end-to-end gate,
   builds, attests and creates a **draft** release. The job summary repeats these steps.
2. Download the whole draft into an **empty folder outside any checkout** and check that CI built it. This step is
   not optional: your signature vouches for whatever `SHA256SUMS` lists, so this is what ties it to the build.
   Anyone who can edit a draft (a stolen token) could swap a binary and the manifest together; only the attestation
   check, pinned to this repository's release workflow and this tag, catches that.

   ```sh
   dir="$(mktemp -d)"
   gh release download vX.Y.Z -R WPTK/cfbtui -D "$dir"
   for f in "$dir"/cfbtui-*; do
     gh attestation verify "$f" -R WPTK/cfbtui \
       --signer-workflow WPTK/cfbtui/.github/workflows/release.yml --source-ref refs/tags/vX.Y.Z || exit 1
   done
   ```

   (Untested against a draft release: if `gh release download` cannot read a draft, fetch the assets from the
   run's artifacts with `gh run download` instead.)
3. Sign from a checkout of the tagged commit (so the embedded keys are the ones the release carries), with the key
   stick plugged in:

   ```sh
   python scripts/sign_sums.py sign /path/to/offline/cfbtui-signing.key "$dir/SHA256SUMS"
   python scripts/sign_sums.py verify "$dir/SHA256SUMS" "$dir/SHA256SUMS.sig"
   ```

   `sign` first re-hashes every file in the folder against the manifest and refuses if one is missing, extra or
   different, and it refuses a key that is not embedded in `cfbtui/sigverify.py`, so the wrong key file fails loudly.
4. Upload the signature and publish:

   ```sh
   gh release upload vX.Y.Z "$dir/SHA256SUMS.sig" -R WPTK/cfbtui
   gh release edit vX.Y.Z -R WPTK/cfbtui --draft=false
   ```

   Upload the signature before publishing: with immutable releases on, a published release cannot take new assets.
5. Unplug the stick. Auto-updating users now pick the release up; anyone running a build with placeholder keys or a
   release published without `SHA256SUMS.sig` is only shown the link, never updated.

## If a key is lost or leaked

Installed copies trust both embedded keys, so the spare can sign a release that rotates the keys:

1. In a new commit set `KEY_CURRENT` to the old spare's public key and `KEY_SPARE` to a freshly generated key
   (`keygen` again; store it as above). Cut a release and sign it **with the old spare**. Installed copies accept it
   because the spare is one of their keys, and from then on they trust the new pair.
2. Destroy the lost or leaked seed. Note the incident in the changelog.

Limits to know about:

- A lost key with a good copy of the spare is routine.
- A **leaked** key is worse than the rotation suggests. An install that takes one update signed by the thief runs the
  thief's code, which can replace the embedded keys or switch updating off, so that install never takes the rotation
  release. Treat those installs as lost: announce it and tell users to reinstall by hand from the release page.
- The rotation release must be a minor or patch bump: the updater only announces a new major version, it never
  installs it unasked.
- If both keys are lost or leaked, no release can reach installed copies safely; users must download a new binary by
  hand, and the README should say so.
- A signature does not carry a version or an expiry. Anyone who can publish a release can make an older signed
  release "latest" again (installs only move to versions newer than their own, and the binary must report the
  tag's version), or hold updates back by publishing nothing. Immutable releases limit this once enabled.

## Verifying by hand

`python scripts/sign_sums.py verify SHA256SUMS SHA256SUMS.sig` checks a downloaded pair against the keys in the
checkout. The README also describes `gh attestation verify` (and `gh release verify`, which works once immutable
releases are on) for people who want a check that does not depend on these keys.
