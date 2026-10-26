# Signing releases

For the owner. The self-updater installs a new binary only if the release's `SHA256SUMS` carries a valid Ed25519
signature (`SHA256SUMS.sig`) from a key built into the app. The private key lives offline with you and never on
GitHub, so someone who can publish a GitHub release (a stolen token, a compromised workflow) still cannot make an
installed cfbtui accept their file. Releases up to 1.5.0 do not check anything; the protection starts with the first
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

Each command writes a private seed (mode 600, never overwrites a file) and prints `public key: ...`. Put the first
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
2. Optional check that the draft is what CI built (recommended; the signature will vouch for whatever is in
   `SHA256SUMS`):

   ```sh
   gh release download vX.Y.Z -R WPTK/cfbtui -D check --clobber
   (cd check && sha256sum -c SHA256SUMS)          # macOS: shasum -a 256 -c SHA256SUMS
   gh attestation verify check/cfbtui-linux-x86_64 -R WPTK/cfbtui   # and one or two others
   ```
3. Sign the manifest you just checked (the key stick plugged in, the passphrase entered):

   ```sh
   python scripts/sign_sums.py sign /path/to/offline/cfbtui-signing.key check/SHA256SUMS
   python scripts/sign_sums.py verify check/SHA256SUMS check/SHA256SUMS.sig
   ```

   `sign` refuses to sign with a key that is not embedded in `cfbtui/sigverify.py`, so using the wrong key file fails
   loudly. Run it from a checkout of the tagged commit so the embedded keys are the ones the release carries.
4. Upload the signature and publish:

   ```sh
   gh release upload vX.Y.Z check/SHA256SUMS.sig -R WPTK/cfbtui
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

Limits to know about: a lost key with a good copy of the spare is routine. If a key was leaked rather than lost, the
thief can sign updates that old installs accept until those installs take the rotation release, so rotate quickly and
announce it. If both keys are lost or leaked, no release can reach installed copies safely; users must download a new
binary by hand from the release page, and the README should say so.

## Verifying by hand

`python scripts/sign_sums.py verify SHA256SUMS SHA256SUMS.sig` checks a downloaded pair against the keys in the
checkout. The README also describes `gh release verify` and `gh attestation verify` for people who want
a check that does not depend on these keys.
