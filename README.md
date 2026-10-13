# cfbtui

[![CI](https://github.com/WPTK/cfbtui/actions/workflows/ci.yml/badge.svg)](https://github.com/WPTK/cfbtui/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/WPTK/cfbtui)](https://github.com/WPTK/cfbtui/releases/latest)
![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)
[![License: MIT](https://img.shields.io/github/license/WPTK/cfbtui)](LICENSE)

A college football scoreboard for your terminal. Live scores, rankings and scoring plays for every FBS and FCS game, in one window.

![The scoreboard](docs/img/grid.png)

- [Features](#features)
- [Install](#install)
- [Usage](#usage)
- [Keys](#keys)
- [Command-line options](#command-line-options)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Privacy and data source](#privacy-and-data-source)
- [Development](#development)
- [License](#license)

## Features

- Every FBS and FCS game for the week, live ones first, then upcoming, then finished.
- Updates on its own: every 20 seconds while you're at the computer, every 2 minutes once you've stepped away.
- Live cards show the clock, down and distance, and who has the ball. A card flashes when someone scores.
- Upset alerts: when a ranked team is losing, or lost, to a worse-ranked or unranked team, its card gets a yellow border and an UPSET label.
- A ticker of scores, kickoffs and upsets as they happen.
- Game detail with every scoring play and win probability.
- AP and Coaches polls, switching to the CFP ranking once the committee releases it.
- Starred favorites pinned at the top, saved between runs.
- Filters for Top 25, live games and favorites, plus a conference picker.
- Cards or a one-line-per-game list.
- Any week of the season, plus Bowls and the Playoff.
- Copy a game, or the whole board, for pasting into Discord.
- A notice when a newer version is out.

## Install

1. Download `cfbtui.exe` from the [latest release](https://github.com/WPTK/cfbtui/releases/latest).
2. Open Windows Terminal, go to the folder you saved it in, and run `.\cfbtui.exe`.

There is nothing else to install. You need a terminal that shows colors and Unicode; Windows Terminal does.
The old Command Prompt window does not.

The exe is not code-signed yet, so Windows may warn about an unrecognized app the first time. Choose
**More info**, then **Run anyway**. Each release also carries a `.sha256` file if you want to check the download.

## Usage

Run `cfbtui.exe` and the current week's games appear. Use the arrow keys to move between cards and press
`Enter` to open one.

![Game detail](docs/img/detail.png)

**Favorites.** Press `1` or `2` to star the away or home team of the selected game. Starred teams' games move
to a Favorites section at the top.

**Rankings.** `R` shows the AP and Coaches polls. Once the College Football Playoff committee releases its
first ranking, you see only the CFP ranking through the end of the season. The FCS board shows the FCS
Coaches poll.

![Rankings](docs/img/rankings.png)

**Views.** `v` switches between cards and a one-line-per-game list. `l` cycles the filter and `o` opens the
conference picker.

![One line per game](docs/img/list.png)

![Conference picker](docs/img/conferences.png)

**Discord.** `c` copies one game as a line of text with the winner in bold. `C` copies the board as a code
block. Discord caps messages at 2,000 characters, so on a big Saturday `C` copies one part at a time; press
it again for the next part.

## Keys

| Key | What it does |
|---|---|
| arrow keys | Move between games |
| `Enter` | Open the game: every scoring play and win probability |
| `R` | Rankings |
| `[` `]` | Previous / next week. After week 15 come **Bowls** and the **Playoff** |
| `t` | Back to this week |
| `f` | Switch between FBS and FCS |
| `l` | Filter: all games, Top 25, live only, favorites |
| `o` | Pick a conference |
| `v` | Switch between cards and a one-line-per-game list |
| `1` `2` | Star the away / home team of the selected game |
| `c` | Copy the selected game for Discord |
| `C` | Copy every game on screen for Discord |
| `r` | Refresh now |
| `g` | Change the icon style |
| `Esc` | Close a screen |
| `q` | Quit |

## Command-line options

These apply to that run only.

```
cfbtui.exe --week 9              start on week 9 (also: --week bowls, --week playoff)
cfbtui.exe --group fcs           start on the FCS board
cfbtui.exe --glyphs unicode      icon style: ascii, unicode, emoji, nerd
cfbtui.exe --layout list         one line per game
cfbtui.exe --no-update-check     don't look for a newer version
cfbtui.exe --no-config           ignore and never touch the settings file
cfbtui.exe --version
```

## Configuration

cfbtui creates `%LOCALAPPDATA%\cfbtui\config.toml` the first time you star a team. You can edit it in
Notepad. Anything you leave out uses the default, and a bad value is ignored with a warning.

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

[updates]
check = true       # set to false to never check for a newer version
```

## Troubleshooting

**Icons show as empty boxes.** The default `nerd` icon style needs a [Nerd Font](https://www.nerdfonts.com/)
set as your terminal's font. Press `g` to cycle to another style, or start with `--glyphs unicode`.

![Unicode icons](docs/img/grid-unicode.png)

**"Could not reach ESPN."** cfbtui keeps retrying and backs off between attempts. Check your connection; if
the rest of the internet works, ESPN's service may be down.

**No games listed.** The week may have no games, or the filter and conference may be hiding them. The
bottom bar shows the active filter. Press `l` until it says all games, and `t` to return to this week.

## Privacy and data source

Scores come from ESPN's public scoreboard service, which is unofficial and undocumented and can change or
disappear without warning. cfbtui is an independent project, not affiliated with ESPN or the NCAA.

At startup it also asks GitHub whether a newer release exists. That is the only other request it makes, and
it sends no personal information. Turn it off with `--no-update-check` or `check = false` in the settings
file.

## Development

Building from source, running the tests and cutting a release: [docs/development.md](docs/development.md).

## License

MIT. See [LICENSE](LICENSE).
