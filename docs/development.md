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

Writes `dist\cfbtui.exe` and `dist\cfbtui.exe.sha256`. It signs the exe first when the signing secrets are set;
see [signing.md](signing.md).

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

## Releasing

1. Finish the work, add a section to `CHANGELOG.md`, bump the version with
   `python -m cfbtui.version bump minor --write` (never edit `__version__` by hand).
2. Commit and push to `main`.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`. The release workflow checks the tag against the
   version and the changelog, runs the tests on Windows, Linux and macOS, then builds in parallel and publishes
   one release carrying:

   | File | Built on |
   |---|---|
   | `cfbtui-windows-x86_64.exe` (signed when the secrets exist) | `windows-latest` |
   | `cfbtui-linux-x86_64` | `ubuntu-latest`, inside `python:3.13-bullseye` |
   | `cfbtui-linux-arm64` | `ubuntu-24.04-arm`, inside `python:3.13-bullseye` |
   | `cfbtui-macos-arm64` | `macos-latest` |
   | `cfbtui-macos-x86_64` | `macos-15-intel` (GitHub's last Intel image, gone August 2027) |
   | `cfbtui-X.Y.Z.tar.gz` and `cfbtui-X.Y.Z-py3-none-any.whl` | `ubuntu-latest` |
   | `SHA256SUMS` for all of the above | |

   plus that version's changelog section as the release notes. Every binary answers `--version`, `--help` and
   `--selftest` on its builder before it is uploaded, and the wheel is installed into a clean venv and run the
   same way. If any job fails, nothing is published.

Before announcing a release, run through [smoke-test.md](smoke-test.md) on a machine without Python.

## Conventions

Versions are FibVer: each part advances to the next Fibonacci number (0, 1, 2, 3, 5, 8, 13 ...). Use
`python -m cfbtui.version bump {major|minor|patch} --write` rather than editing `__version__` by hand.
The changelog is written as a simulation log, one event per bullet.
