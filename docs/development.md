# Development

Python 3.13 and Textual. Scores come from ESPN's unofficial site API; there is no key.

## Run from source

Windows:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m cfbtui
```

macOS and Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m cfbtui
```

## Tests and checks

```powershell
.venv\Scripts\python -m pytest
```

Tests run against saved payloads in `tests/fixtures/` and a fake client; none touch the network. CI runs them
on Windows, Linux and macOS, so a change that works here but leans on a Windows path or encoding will show up
there.

## Build a binary

On Windows:

```powershell
scripts\build_exe.ps1
```

Writes `dist\cfbtui.exe` and `dist\cfbtui.exe.sha256`. The exe is not code-signed; see [signing.md](signing.md).

Anywhere else the same spec builds `dist/cfbtui`. Install `tzdata` first so the binary carries its own zone
files and does not depend on the target machine's:

```sh
.venv/bin/python -m pip install tzdata
.venv/bin/python -m PyInstaller --noconfirm --clean --workpath .pyi-build cfbtui.spec
./dist/cfbtui --selftest
```

PyInstaller does not cross-compile: a binary runs on the kind of machine that built it, and a Linux binary
needs a glibc at least as new as the builder's. The release workflow builds the Linux binaries inside a
Debian 11 container (glibc 2.31) so they run on distributions back to 2020.

## Test the self-updater end to end

The self-updater swaps the running binary, which unit tests only simulate. The `Updater end-to-end` workflow
(`.github/workflows/updater-e2e.yml`) runs by hand (`workflow_dispatch`) and, as a gate, from `release.yml` on the
tagged commit: no draft release is created unless it passes. It builds the real binary on Windows, Linux and macOS
at the current version and at the next patch version, serves the newer one from a throwaway server on `127.0.0.1`
inside the job with a `SHA256SUMS` signed by a throwaway key, and checks that the older one installs it, that a
wrong checksum, a manifest changed after signing, a manifest signed by an untrusted key and a release with no
`SHA256SUMS.sig` each change nothing, and that "Restart now" lands in the new version. The throwaway key is made in
the job and written into the scratch checkout's `cfbtui/sigverify.py` only (`updater_e2e.py embed-key`); the real
keys are never involved. The checks live in `scripts/updater_e2e.py`; to run them locally, in a scratch copy of the
checkout (the version bump and the embedded key must never reach a commit), embed the key, build the two binaries
and pass them in:

```sh
python scripts/updater_e2e.py embed-key KEYFILE          # KEYFILE outside the checkout
# build OLD_BINARY, bump the patch version, build NEW_BINARY (see the workflow)
python scripts/updater_e2e.py OLD_BINARY NEW_BINARY OLD_VERSION NEW_VERSION SCRATCH_DIR KEYFILE
```

Two things exist only for this test:

- `CFBTUI_RELEASES_URL` replaces the GitHub release feed URL. It is honoured only when its host is exactly
  `127.0.0.1` (http or https); any other value is ignored and GitHub is asked as usual. Asset downloads are already
  limited to https or `http://127.0.0.1`.
- `cfbtui --update-test apply|restart` runs the update path without the TUI: check, stage, probe, install, and for
  `restart` start the installed binary. The TUI cannot be driven in CI, so this reuses the same `Updater`,
  `install_update` and `restart` that the app calls on quit. It needs a standalone binary, ignores your config and is
  hidden from `--help`.

## Screenshots

`scripts\screenshot_terminal.ps1` captures the README images from a real Windows Terminal window, so they
look the way the app looks. It renders the window with `PrintWindow` and posts keys straight to it, so it
never needs keyboard focus and whatever is in front of it stays out of the shot. Run it on a Saturday for a
busy board; it uses live ESPN data.

```powershell
$sc = "scripts\screenshot_terminal.ps1"
& $sc -Name grid
& $sc -Name grid-unicode -Glyphs unicode
& $sc -Name grid-ascii -Glyphs ascii
& $sc -Name list -Keys "v"
& $sc -Name conferences -Keys "o"
& $sc -Name detail -Week 6 -Keys "{RIGHT},{ENTER}" -Height 700
& $sc -Name rankings -Keys "R" -Height 820
```

Keys are comma-separated: plain characters, or `{RIGHT}`, `{LEFT}`, `{UP}`, `{DOWN}`, `{ENTER}`, `{ESC}`.
`-Week` picks a past week when you want finished games. `-Width` and `-Height` are physical pixels. Output
goes to `docs/img/`.

## Locked dependencies for release builds

`pyproject.toml` keeps version ranges, and `ci.yml` installs from them so a new upstream release shows up as a CI
failure early. The release and updater e2e workflows instead install from `uv.lock` (`uv sync --locked`, with the
`dev` and `binary` extras), so a shipped binary is built from the locked set of packages (the uv version and the setuptools build backend are the exceptions), and the lock
records a hash for every file. `--locked` fails the build if `pyproject.toml` and the lock disagree.

Refresh it when dependencies change (a Dependabot PR, or a deliberate bump), with the uv version the workflows pin
(`UV_VERSION` in `release.yml`):

```sh
python -m pip install uv==0.13.0
uv lock --upgrade            # or: uv lock, after editing pyproject.toml
uv sync --locked --extra dev --extra binary
python -m pytest
```

Commit `uv.lock` with the change. Lock updates need the same review as code: they are what ships.

## Releasing

1. Finish the work, add a section to `CHANGELOG.md`, bump the version with
   `python -m cfbtui.version bump minor --write` (never edit `__version__` by hand).
2. Commit and push to `main`.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`. The release workflow checks the tag against the
   version and the changelog (and that the release signing keys in `cfbtui/sigverify.py` are filled in), runs the
   tests on Windows, Linux and macOS and the updater end-to-end test, then builds in parallel, attests the build
   provenance and creates a **draft** release carrying:

   | File | Built on |
   |---|---|
   | `cfbtui-windows-x86_64.exe` (not code-signed) | `windows-latest` |
   | `cfbtui-linux-x86_64` | `ubuntu-latest`, inside `python:3.13-bullseye` |
   | `cfbtui-linux-arm64` | `ubuntu-24.04-arm`, inside `python:3.13-bullseye` |
   | `cfbtui-macos-arm64` | `macos-latest` |
   | `cfbtui-macos-x86_64` | `macos-15-intel` (GitHub's last Intel image, gone fall 2027) |
   | `cfbtui-X.Y.Z.tar.gz` and `cfbtui-X.Y.Z-py3-none-any.whl` | `ubuntu-latest` |
   | `SHA256SUMS` for all of the above | |

   plus that version's changelog section as the release notes. Every binary answers `--version`, `--help` and
   `--selftest` on its builder before it is uploaded, and the wheel is installed into a clean venv and run the
   same way. If any job fails, no release is created.
4. Sign and publish by hand: sign `SHA256SUMS` with the offline key, upload `SHA256SUMS.sig`, publish the draft.
   The exact commands are in the job summary and in [release-signing.md](release-signing.md). A release without
   `SHA256SUMS.sig` is never installed by the updater, only announced.

Release binaries are not byte-reproducible (two PyInstaller builds of one commit gave different hashes), so nobody
can rebuild and compare; trust rests on the signature on `SHA256SUMS` and on the build attestations.

Before announcing a release, run through [smoke-test.md](smoke-test.md) on a machine without Python.

## Conventions

Versions are FibVer: each part advances to the next Fibonacci number (0, 1, 2, 3, 5, 8, 13 ...). Use
`python -m cfbtui.version bump {major|minor|patch} --write` rather than editing `__version__` by hand.
The changelog is written as a simulation log, one event per bullet.
