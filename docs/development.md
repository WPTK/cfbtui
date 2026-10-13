# Development

Python 3.13 and Textual. Scores come from ESPN's unofficial site API; there is no key.

## Run from source

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m cfbtui
```

## Tests and checks

```powershell
.venv\Scripts\python -m pytest
```

Tests run against saved payloads in `tests/fixtures/` and a fake client; none touch the network.

## Build the exe

```powershell
scripts\build_exe.ps1
```

Writes `dist\cfbtui.exe` and `dist\cfbtui.exe.sha256`. It signs the exe first when the signing secrets are set;
see [signing.md](signing.md).

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
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`. The release workflow tests, builds, and publishes
   `cfbtui.exe` with its SHA-256 and that version's changelog section.

Before announcing a release, run through [smoke-test.md](smoke-test.md) on a machine without Python.

## Conventions

Versions are FibVer: each part advances to the next Fibonacci number (0, 1, 2, 3, 5, 8, 13 ...). Use
`python -m cfbtui.version bump {major|minor|patch} --write` rather than editing `__version__` by hand.
The changelog is written as a simulation log, one event per bullet.
