# cfbtui

## What it is

A Textual terminal UI for college football: live scores, rankings, game detail and scoring plays. Data comes from
ESPN's unofficial public JSON endpoints (no key). Ships as PyInstaller one-file binaries for five platforms (Windows,
Linux x86_64/arm64, macOS arm64/x86_64) plus an sdist and wheel, all on one GitHub release. Standalone builds update
themselves (checksum-verified swap on quit); pip/pipx/uv installs only get an upgrade message.

## Status and non-goals

- The project is in an audit to reach a settled state. No new features unless the owner accepts one at a meeting
  gate. (A News tab is being scoped in a later meeting; it is not decided, so do not build it.)
- ESPN's API is unofficial and can change without notice; parsing must stay tolerant and tests use saved payloads.
- Python 3.13+ only (`requires-python = ">=3.13"`).

## Layout

- `cfbtui/espn/` ESPN HTTP client, parsing, models, period/clock helpers.
- `cfbtui/state/` the game store, event detection (`events.py`) and upset logic (`upset.py`).
- `cfbtui/ui/` Textual widgets, screens (`screens/`), glyphs, theme, `app.tcss`.
- `cfbtui/app.py` the Textual app; `__main__.py` CLI; `config.py` TOML config; `poll.py` poll scheduler and freshness.
- `cfbtui/update.py` release check; `cfbtui/selfupdate.py` download, verify and swap the binary.
- `cfbtui/version.py` FibVer bump tool; `cfbtui.spec` PyInstaller spec.
- `scripts/` build, hash, sign and screenshot scripts; `updater_e2e.py`; `spot_check.py`.
- `tests/` pytest suite (no network); `tests/uat/` user-journey tests (`test_uat_live.py` needs `CFBTUI_LIVE=1`).
- `tests/fixtures/` saved ESPN payloads (`pairs/` holds hand-edited before/after pairs).
- `docs/` development, signing and smoke-test guides, README images.
- `.github/workflows/` `ci.yml`, `release.yml`, `updater-e2e.yml`.

## Commands

Full procedures are in `docs/development.md`; do not duplicate them here. Windows paths shown; use `.venv/bin/python`
elsewhere.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m cfbtui                      # run (add --config PATH or --no-config)
.venv\Scripts\python -m ruff check .                # lint, as CI
.venv\Scripts\python -m vulture cfbtui scripts --min-confidence 80
.venv\Scripts\python -m pytest                      # tests
.venv\Scripts\python -m cfbtui --version
scripts\build_exe.ps1 -SkipSign                     # builds dist\cfbtui.exe
dist\cfbtui.exe --selftest
```

Updater end to end (manual workflow `updater-e2e.yml`; local run needs two binaries built from a scratch checkout with
the version bumped, never in a commit): `python scripts/updater_e2e.py OLD NEW OLD_VERSION NEW_VERSION SCRATCH_DIR`.

## PR flow

- One branch per change, PR to `main`; merge on green CI on the exact head, base merged in, never force-pushed.
- Review is capped per the global CLAUDE.md (one review, one fix push, at most one delta review).
- Keep prose/docs PRs separate from workflow (`.github/`) PRs.
- `ci.yml` has `paths-ignore` for `**.md`, `docs/**` and `LICENSE`, so docs-only PRs run no CI by design.
- CI runs ruff, vulture, pytest and `--version` on Windows, Linux and macOS.

## Changelog and versions

- Every behaviour change gets a `CHANGELOG.md` entry in the existing style (a "Simulation Log", one event per bullet,
  newest first). Docs-only changes such as this file get none.
- The version lives in `cfbtui/__init__.py`. Change it only with `python -m cfbtui.version bump {major|minor|patch}
  --write`; versions are FibVer.
- `release.yml` runs on a `v*` tag, which must match that version and have a `## X.Y.Z (date)` section in the
  changelog.
- Release, tag, sign and publish only on the owner's word.

## Work tracking

GitHub issues for real defects. The audit program's state lives in the coordinator's memory file
`plan-2026-10-26-audit-program.md`; do not copy it here.

## Gotchas

- `tests/fixtures/**/*.json` are `-text` in `.gitattributes`: never let line-ending normalisation touch them.
- `.pyi-build/` is the PyInstaller work dir (gitignored).
- The Windows exe is currently unsigned (`docs/signing.md`); the SHA256SUMS file guards against corruption only.
- PyInstaller does not cross-compile; Linux binaries are built in a Debian 11 container for glibc 2.31.
- `CFBTUI_RELEASES_URL` is honoured only for host `127.0.0.1`; it exists for the updater e2e test.
- `.ps1` files are CRLF, everything else LF (`.gitattributes`).
