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

`scripts\screenshots.py` renders the README images into `docs/img/` from live ESPN data, so run it on a
Saturday for a busy board. `--fixtures` renders from the saved test payloads instead.

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
