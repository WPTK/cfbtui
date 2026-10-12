# Fresh-machine smoke test

Run this against the exe from a release (or `dist\cfbtui.exe` after `scripts\build_exe.ps1`) on a machine or
Windows profile with no Python and no checkout of the repo. Run it in Windows Terminal.

Record the date, the exe's SHA-256 and the result of each line.

## Setup

- [ ] Copy `cfbtui.exe` into an empty folder, for example `C:\Temp\cfbtui-test`. Run everything from there.
- [ ] `(Get-FileHash cfbtui.exe -Algorithm SHA256).Hash` matches the `cfbtui.exe.sha256` attached to the release.
- [ ] Delete `%LOCALAPPDATA%\cfbtui` if it exists, so the run starts without a config file.
- [ ] `python --version` fails or you are on a profile without Python (proves the exe stands alone).

## Command line

- [ ] `.\cfbtui.exe --version` prints `cfbtui 1.0.0` (or the release's version).
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

## Offline

- [ ] Disconnect the network and start the exe: the status bar shows an error and cards or an empty board, no crash. Reconnect: it recovers on its own.

## Result

Date: ____  Version: ____  SHA-256: ____  Terminal / font: ____  Pass / fail: ____  Notes:
