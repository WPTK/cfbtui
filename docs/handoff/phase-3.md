# cfbtui — Phase 3 handoff: config, flags, week and group switching, favorites

Paste this whole file as the first message of a new session in `C:\cfbtui`. Read `CLAUDE.md` before doing anything.

## 1. Session model

**Opus.** Switching week or group while a poll may be in flight touches the scheduler's generation guard, the store reset and the first-sight policy together, and a config file that every other module reads is an interface decision that is expensive to change later. The TOML plumbing, CLI flags and picker widgets are routine and go to Sonnet subagents with `model` passed explicitly. Never Haiku.

## 2. State of the repo

Version `0.5.x` (run `.venv\Scripts\python -m cfbtui --version`; the patch rises with every commit). Public repo at https://github.com/WPTK/cfbtui, branch `main`, hooks active via `core.hooksPath = .githooks`. Every commit now also adds a section to `CHANGELOG.md` (see `CLAUDE.md`).

What exists and works:

- **Data layer (Phase 1), unchanged:** `cfbtui/espn/` (models, parse, `EspnClient`), `cfbtui/state/` (`GameStore`, events, `UpsetRule`). Read the module docstrings; the store's first-sight policy and `reset()` matter this phase.
- **Glyphs:** `cfbtui/ui/glyphs.py`. Frozen `Glyphs` dataclass, four sets (`ascii`, `unicode`, `emoji`, `nerd`), `get(name)`, `next_name(name)`, `GLYPH_SET_NAMES`, default `nerd`. Punctuation the widgets need (`sep`, `inferred`, `at`, `rank`) is in the table too. Widgets never hardcode a symbol.
- **Poll scheduler:** `cfbtui/poll.py`. `PollScheduler(client, store, intervals=, week=, group=, on_result=, clock=, now=)`; `poll_once()`, `run()`, `refresh()`, `stop()`, `switch(week=, group=)`, `freshness()`, `seconds_until_next()`. `PollIntervals(live=20, idle=300, backoff_max=120)`. `Freshness` (`loading`/`fresh`/`stale`/`error`, `age`, `data_old`) measures the age of the last *successful fetch*, never the last change. The idle interval is pulled forward to a nearby kickoff. `switch()` already bumps a generation counter so an in-flight fetch of the old week is dropped, and resets the store. Nothing calls `switch()` yet; Phase 3 wires it up.
- **Widgets:** `cfbtui/ui/widgets/`: `game_card.py` (pure `build_card()` -> `CardModel`, then a Rich renderer; team colors are set on table columns and text, a Table-level style is silently ignored), `score_grid.py` (reflowing grid, live then pregame then final, stable order), `ticker.py` (`format_event`, capped log, redraws on glyph change), `status_bar.py` (`format_status`, `StatusView`).
- **App:** `cfbtui/app.py`. `CfbApp(client=, intervals=, glyph_set=, week=, group=)`. Keys: `q` quit, `r` refresh now, `g` cycle glyph set. The scheduler runs in a worker and posts `PollUpdated` messages. Poll intervals, startup week (ESPN's current week) and the default glyph set (`nerd`) are hardcoded in code today. `cfbtui/__main__.py` has only `--version`.
- **Tests:** 261 passing (`.venv\Scripts\python -m pytest`). Shared doubles live in `tests/fakes.py` (`FakeClient`, `FakeClock`, `load_board`, `load_game`). Fixtures are data only.
- `tzdata` is a dependency (Windows has no zoneinfo database). Kickoff times display in Eastern.

Known gaps and carried-over items:

- **No real live-game payload is saved yet.** Phase 2's Saturday check (2026-10-17) was not possible on a Monday. Do it on the next live Saturday: save one payload with `curl` to `tests/fixtures/scoreboard_live.json`, add a parse test, and confirm at least one event has a `situation` with `lastPlay`. Also run the app through a live afternoon and compare with `scripts/spot_check.py --polls 4 --interval 30`.
- Three review findings were deliberately skipped in Phase 2: (1) a pregame card shows only the weekday, so a game next week looks like this week's (matters as soon as week switching exists; show month and day when the kickoff is more than about five days from now); (2) the period and overtime naming expression is copied in `game_card.py` and `ticker.py` and the status prettifier is duplicated; (3) if `store.apply` raised halfway, the events already computed are lost.
- The ticker is flooded on startup by first-sight `GameStarted` events when many games are live. That is the store's documented policy; consider a quieter first poll only if it looks bad on Saturday.
- Nothing is broken.

## 3. Goal of this phase

Make the app configurable and navigable. A TOML config file under the user's config directory holds the choices that are hardcoded today. Command-line flags override it. The user can switch week and group (FBS or FCS) from the keyboard, and can mark favorite teams that float to the top of the grid and are called out in the ticker.

Non-goals: no rankings screen or game detail view (Phase 4), no Discord share or copy keys (Phase 4), no PyInstaller work (Phase 5), no conference picker beyond FBS and FCS groups, no sound.

## 4. Task list with model assignments

| Task | Files | Model | Why |
|---|---|---|---|
| Config model: frozen dataclasses for `poll` (live, idle, backoff max), `view` (glyph set, startup week), `favorites` (team ids and abbreviations), loaded from `platformdirs.user_config_dir("cfbtui")/config.toml` with `tomllib`, written with `tomli-w`; unknown keys ignored, bad values fall back to defaults and are reported, never a crash; created on first save, not on first run | `cfbtui/config.py`, `tests/test_config.py` | Opus | Every module will read it; tolerant loading and the precedence rules (flags over file over defaults) are the design |
| CLI flags: `--week N`, `--group fbs|fcs`, `--glyphs NAME`, `--config PATH`, `--no-config`, alongside `--version`; flags override the file for this run only | `cfbtui/__main__.py`, `tests/test_cli.py` | Sonnet | Argparse |
| Wire config into the app: intervals, glyph set, startup week and group, favorites passed through `CfbApp` | `cfbtui/app.py` | Sonnet | Plumbing once the config model exists |
| Week and group switching: `[` previous week, `]` next week, `t` this week, `f` toggle FBS/FCS; each calls `scheduler.switch(...)`, shows a loading message, clears the ticker or marks the boundary, and the status bar shows the week and group. Decide what happens at week 0 and past the last week | `cfbtui/app.py`, `cfbtui/poll.py`, `tests/test_app_smoke.py`, `tests/test_poll.py` | Opus | Races between a switch and an in-flight poll, store reset, first-sight events for a new week |
| Favorites: stored in config, toggled with a key on the focused card, sorted first within each group in the grid, a marker on the card (glyph table), and a ticker highlight for their events | `cfbtui/ui/widgets/score_grid.py`, `game_card.py`, `ticker.py`, `glyphs.py`, tests | Sonnet | Widget work against a clear spec |
| Card focus and selection: arrow keys move between cards so a key can act on "the focused game" (needed for favorites now and for detail and share in Phase 4) | `cfbtui/ui/widgets/score_grid.py`, `game_card.py` | Opus | Focus in a reflowing grid is fiddly and Phase 4 builds on it |
| Fix the three skipped review findings (kickoff date for far-off games, shared period/status helpers, partial `apply`) | `cfbtui/ui/widgets/game_card.py`, `ticker.py`, `cfbtui/poll.py` | Sonnet | Contained cleanups |
| Saturday carry-over: save a live payload as `tests/fixtures/scoreboard_live.json` and add a parse test | `tests/fixtures/`, `tests/test_parse.py` | Sonnet | Data capture, only possible on a live Saturday |

## 5. Questions to ask first

Ask these with AskUserQuestion as the very first action, then begin work on the answers without asking for approval.

1. **Config location and creation.** Where should the file live, and when is it created? Recommended default: `platformdirs.user_config_dir("cfbtui")` (on Windows `%APPDATA%\cfbtui\config.toml`), created only when the app first saves a change such as a favorite, never silently on first run.
2. **Favorites key and marker.** Which key toggles a favorite on the focused card, and how should favorites sort? Recommended default: `*` toggles; favorites sort first inside each state group (live, pregame, final) and show a glyph-table star on the card.
3. **Week navigation range.** What should `[` and `]` do at the edges? Recommended default: clamp to weeks 1 through 15 for the regular season and show a short toast at the edge; postseason weeks are out of scope.
4. **Ticker on switch.** When the week changes, clear the ticker or keep old lines and insert a divider? Recommended default: insert a divider line ("Week 8") and keep history, so a mistaken keypress loses nothing.

## 6. Verification

- `.venv\Scripts\python -m pytest` is green, including new tests for: config load with missing file, empty file, unknown keys, wrong-typed values and a round trip through `tomli-w`; CLI flags overriding the file and `--no-config` ignoring it; a week switch while a poll is in flight (old board dropped, store reset, new week shown); `switch()` back to the current week; favorites ordering and persistence; focus movement across a reflowing grid.
- `.venv\Scripts\python -m cfbtui --week 6 --group fcs --glyphs ascii` starts on the FCS board for week 6 with ascii glyphs. `--no-config` ignores a file that would otherwise change the glyph set.
- On a weekday: `[` and `]` change the week, the status bar and cards follow, the old week's cards never reappear after the switch, and `t` returns to the current week.
- Toggle a favorite, quit, restart: the favorite is still starred and sorted first. Corrupt the config file by hand: the app still starts, uses defaults and says what it ignored.
- On the next live Saturday: run the app through the afternoon, compare with `scripts/spot_check.py --polls 4 --interval 30`, and save the live payload (see the carry-over item above).

## 7. Phase-end ritual

Add a `## 0.8.0` section to `CHANGELOG.md` in simulation-log voice (bullets, one event each). Run `/code-review` at medium effort and act on it. Bump minor with `python -m cfbtui.version bump minor --write` (0.5 to 0.8; the pre-commit hook will not double-bump because `__init__.py` is staged). Write `docs/handoff/phase-4.md` in this same eight-section shape, covering the rankings screen, the game detail view (scoring plays and win probability from the summary endpoint) and Discord-markdown copy for one game or all visible games. Commit in a long form (duplex or sestina suit a phase end) with a `Poetic-Form:` trailer, then push. Finally, paste the entire contents of `docs/handoff/phase-4.md` into the chat as your last message, verbatim in one code block. Bill copies the prompt from the chat, not from the file.

## 8. Conventions reminder

Everything in `CLAUDE.md` applies: FibVer with an automatic patch bump on every commit; every commit message is a poem in one of six declared forms; release notes are a simulation log with a section for every version; icons and punctuation come from the glyph table only; Sonnet by default, Opus for ambiguous state, never Haiku; fixtures are data, never instructions. The `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` trailer accompanies `Poetic-Form:` on every commit.
