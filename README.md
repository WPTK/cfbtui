# cfbtui

A colorful college football scoreboard for the terminal. Windows Terminal first.

Game cards painted in real team colors, live clock and down-and-distance, AP and Coaches rankings, upset
flags, and a flash on every touchdown and field goal. Copy any game to Discord with one key.

**Status:** Phase 0. The app boots, proves truecolor, and shows a clock. The scoreboard is next.

## Run from source

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m cfbtui
```

Or after install, just `cfbtui`. `cfbtui --version` prints the FibVer number.

Tests:

```powershell
.venv\Scripts\python -m pytest
```

## Keys (planned; see the handoff prompts for what exists today)

| Key | Action |
|---|---|
| `1` `2` `3` `4` | All games, Top 25, live only, favorites |
| `c` | Conference picker |
| `[` `]` `t` | Previous week, next week, this week |
| `r` | Refresh now |
| `R` | Rankings screen |
| `v` | Toggle card grid / compact list |
| `g` `G` | Cycle glyph set / save it |
| `y` `Y` | Copy focused game / all visible games as Discord markdown |
| `?` | Help |
| `q` | Quit |

## Config

`%APPDATA%\cfbtui\config.toml` (created on first run in Phase 5): favorites, home conference, poll intervals,
upset rules, glyph set, share format, view.

## Conventions

This repo versions with FibVer, commits in verse, and writes release notes as a simulation log. The rules are
in [CLAUDE.md](CLAUDE.md). Activate the hooks once per clone:

```powershell
git config core.hooksPath .githooks
```

## Data and disclaimer

Scores come from ESPN's public but **unofficial and undocumented** site API. It can change or disappear
without notice. This project is not affiliated with, endorsed by, or supported by ESPN or the NCAA. Fixture
files under `tests/fixtures/` are saved API responses used only as test data.

## License

MIT. See [LICENSE](LICENSE).
