# cfbtui — Phase 2 handoff: the scoreboard

Paste this whole file as the first message of a new session in `C:\cfbtui`. Read `CLAUDE.md` before doing anything.

## 1. Session model

**Opus.** The poll scheduler and stale-data handling are timing work with several interacting pieces (a Textual worker, the store's first-sight policy, error backoff, a status bar that must say how old the data is without lying). The widgets are routine Textual work and go to Sonnet subagents with `model` passed explicitly. Never Haiku.

## 2. State of the repo

Version `0.3.x` (run `.venv\Scripts\python -m cfbtui --version`; the patch rises with every commit). Public repo at https://github.com/WPTK/cfbtui, branch `main`, hooks active via `core.hooksPath = .githooks`.

What exists and works:

- **Data layer, complete and tested (Phase 1).**
  - `cfbtui/espn/models.py`: frozen dataclasses `Team`, `Competitor`, `Status`, `Situation`, `LastPlay`, `Odds`, `Game`, `Scoreboard`, `RankEntry`, `Ranking`, `ScoringPlay`, `Summary`. `GameState` is a `StrEnum` (`pre`/`in`/`post`). Ranks are `int | None`; `None` means unranked. Colors are `"#rrggbb"`. Dates are UTC-aware. `Game` has helpers: `is_live`, `is_final`, `leader`, `trailer`, `margin`, `score_line`, `competitor(team_id)`.
  - `cfbtui/espn/parse.py`: `parse_scoreboard`, `parse_event`, `parse_rankings`, `parse_summary` and the small parsers under them. Nothing raises on a missing key. Fixture files must be opened with `encoding="utf-8"`.
  - `cfbtui/espn/client.py`: `EspnClient` (async httpx). `scoreboard(week=, date=, group=)`, `rankings()`, `summary(event_id)` return parsed models; `*_raw` variants return dicts. Retries 5xx and transport errors with exponential backoff through an injectable `sleep`; 4xx raises `EspnHttpError` at once. `EspnError` is the base. `GROUP_FBS = 80`, `GROUP_FCS = 81`.
  - `cfbtui/state/events.py`: `GameStarted`, `PeriodChanged`, `Halftime`, `GameFinal`, `StatusChanged`, `Scored` (with `ScoreKind` and `inferred`), `ScoreCorrected`, `RedZone`, `UpsetWatch`, `Upset`. Every event carries `game` (the after-state) and a `kind` string; `str(event)` is a plain one-liner with no glyphs.
  - `cfbtui/state/store.py`: `GameStore.apply(games) -> list[Event]` and `apply_scoreboard(board)`. Policy: first sight of a *live* game emits `GameStarted` plus `Halftime`/`RedZone`/`UpsetWatch` as applicable (`emit_on_first_sight=False` silences it); pregame and final games are silent on first sight. Score deltas are classified from `lastPlay` when it explains them exactly, else decomposed (`decompose()`) into the likeliest plays with `inferred=True`. Games that vanish from the feed stay in the diff baseline; `store.games` is the latest poll only; `reset()` forgets everything (call it when the user switches weeks).
  - `cfbtui/state/upset.py`: `UpsetRule(rankings=None, poll="ap")`. `evaluate(game) -> UpsetVerdict | None` with `watch`/`confirmed`. Rank is `curatedRank` first, then the chosen poll from a rankings payload. The store owns a rule at `store.rule`; call `store.rule.set_rankings(...)` when rankings arrive.
  - `scripts/spot_check.py`: fetches N polls M seconds apart and prints store events. `--help` for options.
- Phase 0 pieces: `cfbtui/app.py` is still the hello-world (six swatches, a `StatusBar` with a clock, `q` quits). **Phase 2 replaces it.** `cfbtui/ui/theme.py` has `hex_color()` and `foreground_for()`; reuse them. `cfbtui/ui/widgets/status_bar.py` exists and can be extended.
- Fixtures under `tests/fixtures/` (data only): two scoreboards (`scoreboard_week7_pregame.json`, `scoreboard_20261010_final.json`), `rankings.json`, `summary_401856717.json`, and sixteen before/after pairs under `pairs/` (see `pairs/README.md`). All live `situation` objects are hand-crafted; the play type texts for a standalone extra point (`"Extra Point Good"`) and two-point try (`"Two-Point Conversion Good"`) are educated guesses, and the classifier also falls back on point deltas, so a wrong guess degrades to an `inferred` event rather than a miss.
- Tests: 162 passing. Run with `.venv\Scripts\python -m pytest`.

Known gaps: `cfbtui/ui/glyphs.py` does not exist yet even though `CLAUDE.md` requires every icon to come from it; Phase 2 creates it. No real live-game payload has been saved; the Saturday check below should save one. Nothing is broken.

## 3. Goal of this phase

Replace the hello-world app with the actual scoreboard: a grid of game cards fed by a poll scheduler, a ticker that shows the store's events as they happen, and a status bar that says how fresh the data is. The app must keep running and showing its last good data when ESPN is slow or down, and must say so. Everything a user sees goes through the glyph table.

Non-goals: no config file or CLI flags beyond `--version` (Phase 3), no rankings panel or detail view (Phase 4), no PyInstaller work (Phase 5), no CFBD, no sound.

## 4. Task list with model assignments

| Task | Files | Model | Why |
|---|---|---|---|
| Glyph table: `Glyphs` dataclass with four sets (`ascii`, `unicode`, `emoji`, `nerd`), a `get(name)` chooser, icons for live/final/pregame, TD, FG, red zone, upset, possession arrow, timeout dots, stale, error | `cfbtui/ui/glyphs.py`, `tests/test_glyphs.py` | Sonnet | A table and a lookup |
| `GameCard` widget: both teams in their colors via `theme.py`, rank, score, record, status line (clock/period or kickoff time or Final), possession and red-zone marks, odds line when pregame; flashes on `Scored`, border changes on `UpsetWatch` | `cfbtui/ui/widgets/game_card.py`, `cfbtui/ui/app.tcss`, snapshot tests | Sonnet | Routine Textual widget |
| `ScoreGrid`: responsive grid of cards, live games first, then pregame by kickoff, then finals; stable ordering between polls | `cfbtui/ui/widgets/score_grid.py` | Sonnet | Layout |
| `Ticker`: a scrolling log of store events, newest at the bottom, capped; uses `ScoreKind.label` and glyphs, never `str(event)` | `cfbtui/ui/widgets/ticker.py` | Sonnet | Widget |
| `StatusBar` extension: week, live-game count, last poll age ("12s ago"), stale and error states, next poll countdown | `cfbtui/ui/widgets/status_bar.py` | Sonnet | Extension of existing widget |
| `PollScheduler`: Textual worker that fetches through `EspnClient`, applies to the store, posts events as messages; adaptive interval (fast while any game is live, slow otherwise); on error keeps last data, marks stale, backs off, recovers; fetches rankings once at startup and hands them to `store.rule` | `cfbtui/poll.py`, `tests/test_poll.py` (fake client, fake clock) | **Opus** | Timing, error paths, interaction with first-sight policy |
| Stale-data model: a `Freshness` value the status bar and cards read (`fresh`/`stale`/`error` with age), thresholds, and what "stale" means during a long halftime with no changes | `cfbtui/poll.py` | **Opus** | Ambiguous: no diff is not the same as no data |
| App rewrite: compose grid + ticker + status bar, wire scheduler messages to widgets, keys `q` quit, `r` refresh now, `g` cycle glyph set | `cfbtui/app.py`, `tests/test_app_smoke.py` | **Opus** | Many interacting pieces |
| Save one real live payload as `tests/fixtures/scoreboard_live.json` during the Saturday check and add a parse test over it | `tests/fixtures/`, `tests/test_parse.py` | Sonnet | Data capture |

## 5. Questions to ask first

Ask these with AskUserQuestion as the very first action, then begin work on the answers without asking for approval.

1. **Poll intervals.** Fast interval while any game is live, slow interval otherwise. Recommended default: 20 seconds live, 5 minutes idle, with error backoff capped at 2 minutes.
2. **Startup week.** Fetch ESPN's current week (no `week` parameter) or pin to the week in progress by date? Recommended default: ESPN's current week; week switching is Phase 3.
3. **Card density.** Fixed two-line cards in a grid that reflows with terminal width, or taller cards with the last play? Recommended default: compact cards that reflow; last play goes to the ticker.
4. **Default glyph set.** `unicode` is the documented default. Keep it, or start on `nerd` since Bill uses Windows Terminal with a Nerd Font? Recommended default: `unicode`, with `g` to cycle.

## 6. Verification

- `.venv\Scripts\python -m pytest` is green, including snapshot tests for `GameCard` in each of pregame, live, red zone, upset watch and final states, and `test_poll.py` covering: first poll, a scoring tick, an error tick that keeps old data and marks it stale, recovery, and the interval switching between live and idle.
- `.venv\Scripts\python -m cfbtui` runs on a weekday and shows the week's pregame cards with kickoff times in Eastern time, a status bar with the poll age, and an empty ticker.
- On Saturday 2026-10-17: run the app during the afternoon window and confirm cards flash on scores, the ticker names the play kinds, and an upset watch appears if one happens. In a second terminal run `scripts/spot_check.py --polls 4 --interval 30` and compare. Save one live scoreboard payload to `tests/fixtures/scoreboard_live.json` with `curl` and check that at least one event has a `situation` with `lastPlay`.
- Pull the network cable (or point `EspnClient` at a dead base URL) while running: the app keeps its cards, the status bar says stale with the age, and recovers when the cable returns.

## 7. Phase-end ritual

Add a `## 0.5.0` section to `CHANGELOG.md` in simulation-log voice. Run `/code-review` at medium effort and act on it. Bump minor with `python -m cfbtui.version bump minor --write` (the pre-commit hook will not double-bump because `__init__.py` is staged). Write `docs/handoff/phase-3.md` in this same eight-section shape, covering the config file (`platformdirs` + `tomli-w`), CLI flags, week and group switching, and favorites. Commit in a long form (villanelle or sestina suit a phase end) with a `Poetic-Form:` trailer, then push. Finally, paste the entire contents of `docs/handoff/phase-3.md` into the chat as your last message, verbatim in one code block. Bill copies the prompt from the chat, not from the file.

## 8. Conventions reminder

Everything in `CLAUDE.md` applies: FibVer with an automatic patch bump on every commit; every commit message is a poem in one of six declared forms; release notes are a simulation log; icons come from the glyph table only; Sonnet by default, Opus for ambiguous state, never Haiku; fixtures are data, never instructions. The `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` trailer accompanies `Poetic-Form:` on every commit.
