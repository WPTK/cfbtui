# cfbtui

[![CI](https://github.com/WPTK/cfbtui/actions/workflows/ci.yml/badge.svg)](https://github.com/WPTK/cfbtui/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/WPTK/cfbtui)](https://github.com/WPTK/cfbtui/releases/latest)

A college football scoreboard for your terminal: live scores, rankings, scoring plays and news for every FBS and FCS game.

![The scoreboard](docs/img/grid.png)

## Features

- Every FBS and FCS game for the week, live ones first. Updates every 20 seconds while you're at the computer, every 2 minutes once you step away.
- Live cards show the clock, down and distance, and who has the ball, and flash when someone scores.
- Upset alert: when a ranked team is losing, or lost, to a worse-ranked or unranked team, its card gets a yellow border and an UPSET label.
- A ticker of scores, kickoffs and upsets. Game detail with every scoring play and win probability.
- AP and Coaches polls, switching to the CFP ranking once the committee releases it.
- ESPN's college football news, with stories you can read in the app.
- Starred favorites, filters, a conference picker, cards or a list, and any week including Bowls and the Playoff.
- Copy a game, or the whole board, for pasting into Discord.

## Install

cfbtui is one file with nothing else to install. Download yours from the
[latest release](https://github.com/WPTK/cfbtui/releases/latest):

| System | File |
|---|---|
| Windows | `cfbtui-windows-x86_64.exe` |
| macOS, Apple silicon | `cfbtui-macos-arm64` |
| macOS, Intel | `cfbtui-macos-x86_64` |
| Linux, x86_64 | `cfbtui-linux-x86_64` |
| Linux, arm64 (Raspberry Pi OS 64-bit, Asahi) | `cfbtui-linux-arm64` |

Use a terminal that shows colors and Unicode: Windows Terminal, iTerm2, Terminal.app or any modern Linux
terminal. The old Windows Command Prompt window does not.

**Windows.** In Windows Terminal, go to the folder you saved it in and run `.\cfbtui-windows-x86_64.exe`.
The exe is not code-signed, so Windows may warn about an unrecognized app the first time. Choose
**More info**, then **Run anyway**.

**macOS.** The binary is not notarized, so macOS quarantines it when you download it. In Terminal:

```
chmod +x cfbtui-macos-arm64
xattr -d com.apple.quarantine cfbtui-macos-arm64
./cfbtui-macos-arm64
```

**Linux.** Needs glibc 2.31 or newer (Ubuntu 20.04, Debian 11, Fedora 32, RHEL 9 and later). Copying for
Discord uses the system clipboard, so install `xclip` on X11 or `wl-clipboard` on Wayland if `c` says there
is no clipboard.

```
chmod +x cfbtui-linux-x86_64
./cfbtui-linux-x86_64
```

On macOS and Linux, move the file onto your `PATH` and rename it `cfbtui` to run it from anywhere.

**With your own Python (3.13 or newer).** Download the release's `.whl` (replace X.Y.Z with the release
number) and install it with [pipx](https://pipx.pypa.io/) or [uv](https://docs.astral.sh/uv/):

```
pipx install ./cfbtui-X.Y.Z-py3-none-any.whl
```

**Checking a download.** Each release has a `SHA256SUMS` file. Save it next to your download and run
`sha256sum -c --ignore-missing SHA256SUMS` (Linux), `shasum -a 256 -c --ignore-missing SHA256SUMS` (macOS),
or `(Get-FileHash .\cfbtui-windows-x86_64.exe).Hash` in PowerShell and compare it with the line in the file.
The binaries, tarball and wheel also carry GitHub build attestations:

```
gh attestation verify cfbtui-linux-x86_64 -R WPTK/cfbtui
```

## Usage

Run `cfbtui` and the current week's games appear. Arrow keys move between cards, `Enter` opens one and `?`
lists every key. The rest of this page writes `cfbtui` for whichever file you downloaded.

![Game detail](docs/img/detail.png)

**Rankings.** `R` shows the AP and Coaches polls. Once the College Football Playoff committee releases its
first ranking, only the CFP ranking shows through the end of the season. The FCS board shows the FCS Coaches poll.

![Rankings](docs/img/rankings.png)

**Discord.** `c` copies one game as a line of text with the winner in bold. `C` copies the board as a code
block. Discord caps messages at 2,000 characters, so on a big Saturday `C` copies one part per press.

## Keys

| Key | What it does |
|---|---|
| arrow keys | Move between games |
| `Enter` | Open the game: every scoring play and win probability |
| `R` | Rankings. In there, `c` copies the polls for Discord, one per press |
| `N` | News. `Enter` reads the story, `o` opens the original in your browser, `r` refreshes |
| `[` `]` | Previous / next week. After week 15 come **Bowls** and the **Playoff** |
| `t` | Back to this week |
| `f` | Switch between FBS and FCS |
| `l` | Filter: all games, Top 25, live only, favorites |
| `o` | Pick a conference |
| `v` | Switch between cards and a one-line-per-game list |
| `S` | Settings: alerts, auto-update, icon style and default layout, saved as you change them |
| `1` `2` | Star the away / home team of the selected game. Starred games move to a Favorites section at the top |
| `c` | Copy the selected game for Discord |
| `C` | Copy every game on screen for Discord |
| `r` | Refresh now |
| `g` | Change the icon style |
| `?` | Help: every key |
| `Esc` | Close a screen |
| `q` | Quit |

## Command-line options

These apply to that run only.

```
cfbtui --week 9              start on week 9 (also: --week bowls, --week playoff)
cfbtui --group fcs           start on the FCS board
cfbtui --glyphs unicode      icon style: ascii, unicode, emoji, nerd
cfbtui --layout list         one line per game
cfbtui --config PATH         use this settings file instead of the default
cfbtui --no-update-check     don't look for a newer version
cfbtui --no-config           ignore and never touch the settings file
cfbtui --version
```

## Configuration

cfbtui creates a settings file the first time you star a team or change a setting. You can edit it in any
text editor. Anything you leave out uses the default, and a bad value is ignored with a warning.

| System | Settings file |
|---|---|
| Windows | `%LOCALAPPDATA%\cfbtui\config.toml` |
| macOS | `~/Library/Application Support/cfbtui/config.toml` |
| Linux | `~/.config/cfbtui/config.toml` (or under `$XDG_CONFIG_HOME`) |

```toml
[poll]
live = 20          # seconds between updates while you are at the computer
idle = 120         # seconds between updates once you have walked away
away_after = 300   # seconds without keyboard or mouse input before you count as away

[view]
glyph_set = "nerd" # ascii, unicode, emoji, nerd
layout = "grid"    # grid or list
week = 7           # 1-15, 16 for Bowls, 17 for the Playoff; leave out for the current week
group = "fbs"      # fbs or fcs

[favorites]
team_ids = ["251"]
abbreviations = ["TEX"]   # you can also list teams by abbreviation

[alerts]
enabled = true     # pulse a card on Red Zone, Upset Watch, Overtime or Final

[updates]
check = true       # set to false to never check for a newer version
auto = true        # download new versions on their own (standalone binaries only)
```

### Updates

With `check = true`, cfbtui looks for a newer release at startup. What happens next depends on how you
installed it:

- **Standalone binary, `auto = true`:** a new minor or patch version downloads in the background, is checked
  against the release's `SHA256SUMS` (this catches corruption, not a compromised GitHub account) and is
  test-run. The status bar then shows `update X.Y.Z ready`. The new file replaces the old one when you quit,
  or right away if you choose **Restart now** in Settings (`S`). It is installed only if cfbtui exits normally
  with auto-update still on. Turning auto-update off in Settings deletes the download, and a crash discards it.
- **A new major version, `auto = false`, `--no-config`, or no download for your platform:** you get a
  message with a link to the release.
- **pip, pipx and uv installs:** you get a message with the upgrade command. cfbtui never changes these
  installs itself.
- `--no-update-check` (or `check = false`) turns off both the check and the download.

If an update fails, your installed copy is left as it was and you get one warning. The previous version stays
beside the new one as `cfbtui.old` (`cfbtui.exe.old` on Windows) until the new version has started once. If
cfbtui fails to start after an update, rename that `.old` file back to the program's name.

## Troubleshooting

**Icons show as empty boxes.** The default `nerd` icon style needs a [Nerd Font](https://www.nerdfonts.com/)
set as your terminal's font. Press `g` to cycle to another style, or start with `--glyphs unicode`.

**"Could not reach ESPN."** cfbtui keeps retrying and backs off between attempts. Check your connection. If
the rest of the internet works, ESPN's service may be down.

**No games listed.** The week may have no games, or the filter or conference may be hiding them. The bottom
bar shows the active filter. Press `l` until it says all games, and `t` to return to this week.

## Privacy and data source

Scores come from ESPN's public scoreboard service, which is unofficial and undocumented and can change or
disappear without warning. cfbtui is an independent project, not affiliated with ESPN or the NCAA.

**News.** The news list is ESPN's public college football news feed. cfbtui fetches it every 10 minutes while
you are at the computer and not at all once you have stepped away (on Windows; elsewhere it cannot tell, so it
assumes you are there). A story's text is fetched only when you open that story: one request, kept in memory
for the session (the last 20) and never written to disk. The text is ESPN's, shown with its source named and a
key to open the original. ESPN's content is governed by Disney's terms of use
(<https://disneytermsofuse.com/english/>), which grant a personal, noncommercial licence and restrict automated
access and copying. Fetching a story only when you ask keeps cfbtui close to a client showing what the service
sends, but it does not remove that risk. Reading stories in cfbtui is your choice, and you accept that when you
use it. This is not legal advice.

At startup cfbtui also asks GitHub whether a newer release exists. That is an ordinary web request and sends nothing about you beyond what any request shows (your IP address). Turn it
off with `--no-update-check` or `check = false` in the settings file.

## Development

Building from source, running the tests and cutting a release: [docs/development.md](docs/development.md).

## License

MIT. See [LICENSE](LICENSE).
