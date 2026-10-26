# Fresh-machine smoke test

Run this against `cfbtui-windows-x86_64.exe` from a release (or `dist\cfbtui.exe` after `scripts\build_exe.ps1`)
on a machine or Windows profile with no Python and no checkout of the repo. Run it in Windows Terminal. The
same list applies to the macOS and Linux binaries, with that system's terminal and hashing command.

Record the date, the exe's SHA-256 and the result of each line.

## Setup

- [ ] Copy the exe into an empty folder as `cfbtui.exe`, for example `C:\Temp\cfbtui-test`. Run everything from there.
- [ ] `(Get-FileHash cfbtui.exe -Algorithm SHA256).Hash` matches the `cfbtui-windows-x86_64.exe` line in the `SHA256SUMS` attached to the release.
- [ ] Delete `%LOCALAPPDATA%\cfbtui` if it exists, so the run starts without a config file.
- [ ] `python --version` fails or you are on a profile without Python (proves the exe stands alone).

## Command line

- [ ] `.\cfbtui.exe --version` prints `cfbtui X.Y.Z` for the release you are testing.
- [ ] `.\cfbtui.exe --help` lists `--week`, `--group`, `--glyphs`, `--config`, `--no-config`.
- [ ] `.\cfbtui.exe --glyphs bogus` exits with a usage error, not a traceback.

## Running

- [ ] `.\cfbtui.exe` shows team-colored cards within a few seconds, a ticker and a status bar reading `updated Ns ago`.
- [ ] With a Nerd Font the icons are glyphs; without one they are boxes, and `g` or `--glyphs unicode` fixes it.
- [ ] Arrow keys move focus between cards.
- [ ] `Enter` opens the detail screen; scoring plays and a win-probability bar appear on a live or final game; `Esc` returns.
- [ ] `R` opens AP and Coaches polls; `Esc` returns.
- [ ] `c` copies the focused game; paste into Discord or Notepad and check it reads as one line.
- [ ] `C` copies the board; on a full Saturday slate, pressing it again copies the next part.
- [ ] `g` cycles ascii, unicode, emoji, nerd; the status bar names the set.
- [ ] `[` and `]` change the week; `t` returns to this week; `f` toggles FBS and FCS.
- [ ] `q` quits and the terminal is left tidy.

## Config

- [ ] After the runs above, `%LOCALAPPDATA%\cfbtui\config.toml` does **not** exist.
- [ ] Focus a card, press `1` or `2` to star a team; the file now exists and lists it under `[favorites]`.
- [ ] Restart; the starred team is at the top of the grid.
- [ ] `.\cfbtui.exe --no-config` starts with no favorites and does not touch the file.

## Self-update

Needs two builds of the same platform: an older one (A) and a newer patch version (B), for example from two releases
or from a scratch checkout with the version bumped. Normally `Updater end-to-end` covers this; do it by hand once
per release that touches the updater, in a throwaway folder (never the folder of a binary you use). The local
server is `python -m http.server` in a folder holding B as the asset named for your platform
(`cfbtui-windows-x86_64.exe`), `SHA256SUMS` (`<sha256>  <asset name>`) and a `releases/latest` JSON file with
`tag_name`, `html_url` and `assets` entries (`name`, `browser_download_url`, `size`).

- [ ] Copy A into an empty folder; set `CFBTUI_RELEASES_URL=http://127.0.0.1:8000/releases/latest` for the shell.
- [ ] `.\cfbtui.exe --no-config --update-test apply` prints `cfbtui <B> installed`; `.\cfbtui.exe --version` now prints B.
- [ ] On Windows `cfbtui.exe.old` exists. `.\cfbtui.exe --no-config --update-test apply` prints `up to date` and removes it.
- [ ] Put A back and change one character of the hash in `SHA256SUMS`: the run prints `does not match SHA256SUMS`, exits 1, and `.\cfbtui.exe --version` is still A with the file's hash unchanged.
- [ ] Put A back, fix the hash, run `--update-test restart`: it prints B installed, then `cfbtui <B>: up to date` from the restarted binary, with no PyInstaller error text.
- [ ] A `CFBTUI_RELEASES_URL` that is not `127.0.0.1` (for example `http://localhost:8000/...`) is ignored: `--update-test apply` reports up to date, or fails offline, instead of reaching your server.
- [ ] In the real TUI (point at the same server, B newer): the status bar shows the update marker, `Restart now` on the settings screen closes the TUI and opens B.

## Offline

- [ ] Disconnect the network and start the exe: the status bar shows an error and cards or an empty board, no crash. Reconnect: it recovers on its own.

## Result

Date: ____  Version: ____  SHA-256: ____  Terminal / font: ____  Pass / fail: ____  Notes:
