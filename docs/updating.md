# Updating

At startup cfbtui checks GitHub for a newer release when `check = true` (the default). What happens next depends on how you installed it.

| Install | Result |
|---|---|
| Standalone binary, `auto = true`, new minor or patch version | Downloads in the background, verifies the file against the release's `SHA256SUMS`, and test-runs it. The status bar shows `update X.Y.Z ready`. |
| Standalone binary, new major version | Shows a message with a link to the release. |
| Standalone binary with `auto = false`, `--no-config`, or no download for your platform | Shows a message with a link to the release. |
| pip, pipx or uv | Shows a message with the upgrade command. cfbtui never changes these installs. |

The `SHA256SUMS` check catches corruption. It does not protect against a compromised GitHub account (see [signing.md](signing.md)).

To upgrade a PyPI install, run `pipx upgrade cfbtui` (or `uv tool upgrade cfbtui`, or `python -m pip install -U cfbtui`).

## When the new version is installed

The new file replaces the old one when you quit, or right away if you choose **Restart now** in Settings (`S`). It is installed only if cfbtui exits normally and auto-update is still on. Turning auto-update off in Settings deletes the download. A crash discards it.

## Turn updates off

- `--no-update-check` turns off the check and the download for one run.
- `check = false` under `[updates]` in the settings file turns them off for every run.

## If an update fails

Your installed copy is left as it was and you get one warning. The previous version stays beside the new one as `cfbtui.old` (`cfbtui.exe.old` on Windows) until the new version has started once. If cfbtui fails to start after an update, rename that `.old` file back to the program's name.
