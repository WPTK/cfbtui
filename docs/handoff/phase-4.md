# cfbtui — Phase 4 handoff: rankings screen, game detail view, Discord copy

Paste this whole file as the first message of a new session in `C:\cfbtui`. Read `CLAUDE.md` before doing anything.

## 1. Session model

**Opus.** The detail view parses a payload shape (`summary`) that has only one saved fixture, adds a screen stack on top of an app whose polling and focus rules were just made delicate, and the Discord formatter is a text contract other people will paste. The rankings table, the screen widgets and the clipboard plumbing are routine and go to Sonnet subagents with `model` passed explicitly. Never Haiku.

## 2. State of the repo

Version `0.8.x` (run `.venv\Scripts\python -m cfbtui --version`; the patch rises with every commit). Public repo at https://github.com/WPTK/cfbtui, branch `main`, hooks active via `core.hooksPath = .githooks`. Every commit adds a section to `CHANGELOG.md`.

What exists and works:

- **Data layer:** `cfbtui/espn/` (models, parse, `EspnClient` with `scoreboard`, `rankings`, `summary`), `cfbtui/state/` (`GameStore`, events, `UpsetRule`). `GameStore.apply` now isolates a game that raises while diffing: its events are skipped, its old snapshot is kept, and `store.last_errors` lists `(game_id, exception)` for the latest apply. Nothing reads `last_errors` yet.
- **Config (new in Phase 3):** `cfbtui/config.py`. Frozen dataclasses `Config(poll, view, favorites)`, `load_config(path)` (never raises, returns `LoadResult` with warnings), `save_config`, `apply_overrides` for flags, `favorite_ids`. Default path is `platformdirs.user_config_dir("cfbtui")/config.toml`, created on first save only. Favorites are stored as ESPN team ids, plus hand-editable abbreviations.
- **CLI:** `cfbtui/__main__.py` with `--week N`, `--group fbs|fcs`, `--glyphs NAME`, `--config PATH`, `--no-config`, `--version`. `resolve(argv)` is the testable half.
- **App:** `cfbtui/app.py`. `CfbApp(client=, intervals=, glyph_set=, week=, group=, config=, file_config=, config_path=, warnings=)`; explicit arguments beat `config`. Keys: `q` quit, `r` refresh, `g` glyph set, `[` and `]` previous and next week (clamped to 1 to 15 with a toast), `t` current week, `f` toggle FBS and FCS, arrow keys move focus between cards, `1` and `2` star or unstar the focused card's away or home team. A week or group switch clears the grid and the ticker, and the first board of the new view announces nothing. Poll results carry the scheduler's `generation`, and the app ignores any result from an older one. Favorites save through `file_config`, so command-line flags are never written to the file.
- **Widgets:** `ScoreGrid` (favorites first, then live, pregame, final; focus movement via the pure `next_index`; `focused_card`; `clear()`), `GameCard` (focusable, star in the row, kickoff date when more than five days out), `Ticker` (favorite events starred and reversed; `clear_log`, `set_favorites`), `StatusBar` (`Week N FBS`). Shared text helpers live in `cfbtui/ui/labels.py`. Every symbol, including the new `favorite`, comes from the glyph table.
- **Tests:** 331 passing (`.venv\Scripts\python -m pytest`). Doubles in `tests/fakes.py`; Phase 3 app tests use a `WeekClient` in `tests/test_app_phase3.py` that serves a board per week and group and can hold a fetch open.

Known gaps and carried-over items:

- **No real live-game payload is saved yet.** Phase 2 and Phase 3 both landed on weekdays. On the next live Saturday save one payload with `curl` to `tests/fixtures/scoreboard_live.json`, add a parse test, confirm at least one event has a `situation` with `lastPlay`, and compare a live afternoon with `scripts/spot_check.py --polls 4 --interval 30`.
- **Favorites are a block at the top of the grid, not a labelled section.** Bill asked for "their own top section"; a header row would need a second grid. Decide in this phase whether it is worth it.
- **Starring uses `1` and `2`, not `*`.** A game has two teams, and one key could not say which. Revisit if it feels wrong.
- `store.last_errors` is never surfaced. A game whose diff raises every poll fails silently.
- The far-kickoff date on a pregame card is computed when the card repaints, so it does not change on its own as the game approaches.
- Arrow keys on a focused grid now move card focus instead of scrolling; PageUp and PageDown still scroll.
- Nothing is broken.

## 3. Goal of this phase

Add three things on top of the grid: a rankings screen (AP and Coaches polls), a game detail view for the focused card (scoring plays and win probability from the `summary` endpoint), and a Discord-markdown copy of one game or of every visible game, put on the clipboard. Detail and rankings are screens pushed over the grid with `Esc` to return; polling continues underneath.

Non-goals: no PyInstaller work (Phase 5), no conference picker, no sound, no play-by-play beyond scoring plays, no posting to Discord (copy only).

## 4. Task list with model assignments

| Task | Files | Model | Why |
|---|---|---|---|
| Summary parser: scoring plays and win probability from the saved `summary_401856717.json`, tolerant of missing keys; models for both | `cfbtui/espn/models.py`, `cfbtui/espn/parse.py`, `tests/test_parse.py` | Opus | One fixture, an undocumented shape; decide what "missing win probability" looks like |
| Detail screen: pushed on `Enter` from the focused card, fetches `summary` once on open and refreshes while the game is live, shows scoring plays and a win probability bar, handles a failed fetch | `cfbtui/ui/screens/detail.py`, `cfbtui/app.py`, tests | Opus | A second fetch loop beside the scheduler; must stop on pop and survive a week switch underneath |
| Rankings screen: AP and Coaches tables from `client.rankings()`, key `R`, shows the poll date | `cfbtui/ui/screens/rankings.py`, `cfbtui/app.py`, tests | Sonnet | Table rendering against a clear spec |
| Discord formatter: pure functions `format_game(game, glyphs)` and `format_board(games, glyphs)` returning Markdown that fits Discord's 2000 character limit (split into several messages when it does not) | `cfbtui/share.py`, `tests/test_share.py` | Opus | A text contract; length splitting and escaping need care |
| Copy keys: `c` copies the focused game, `C` copies all visible games, via `pyperclip`; a toast on success; a clear message when no clipboard is available | `cfbtui/app.py`, tests | Sonnet | Plumbing; fake the clipboard in tests |
| Surface `store.last_errors` (a status bar count or a ticker line) | `cfbtui/app.py`, `cfbtui/ui/widgets/status_bar.py` | Sonnet | Small, contained |
| Saturday carry-over: save a live payload as `tests/fixtures/scoreboard_live.json` and add a parse test | `tests/fixtures/`, `tests/test_parse.py` | Sonnet | Data capture, only possible on a live Saturday |

## 5. Questions to ask first

Ask these with AskUserQuestion as the very first action, then begin work on the answers without asking for approval.

1. **Discord format.** Plain Markdown lines, or a code block per board? Recommended default: one line per game in plain Markdown with the glyph set forced to `unicode` (Discord renders emoji and unicode but not Nerd Font glyphs), wrapped in a code block only for the all-games copy so columns line up.
2. **Detail view key.** Which key opens the detail view? Recommended default: `Enter` on the focused card, `Esc` to close.
3. **Win probability display.** A text bar, or a number only? Recommended default: a one-line bar built from the glyph table plus the percentage, and nothing at all when ESPN has no win probability for the game.
4. **Favorites section.** Keep favorites as a block at the top of the grid, or add a labelled header row? Recommended default: keep the block; a header costs a second grid for little gain.

## 6. Verification

- `.venv\Scripts\python -m pytest` is green, including new tests for: the summary parser on the saved fixture and on a payload with every optional key removed; the detail screen opening, refreshing, failing and closing without leaving a fetch loop behind; opening detail then switching week underneath; the rankings screen with a failed fetch; Discord output under and over the 2000 character limit; copy with and without a clipboard.
- On a weekday: `Enter` on a final game shows its scoring plays; `R` shows both polls; `c` and `C` put sensible Markdown on the clipboard and pasting it into a Discord message looks right.
- On the next live Saturday: open the detail view on a live game and watch it update; run the app through the afternoon, compare with `scripts/spot_check.py --polls 4 --interval 30`, and save the live payload (see the carry-over item above).

## 7. Phase-end ritual

Add a `## 0.13.0` section to `CHANGELOG.md` in simulation-log voice (bullets, one event each). Run `/code-review` at medium effort and act on it, then call ReportFindings again with outcomes. Bump minor with `python -m cfbtui.version bump minor --write` (0.8 to 0.13; the pre-commit hook will not double-bump because `__init__.py` is staged). Write `docs/handoff/phase-5.md` in this same eight-section shape, covering the PyInstaller exe, the first shipped build (version 1.0.0), the README with screenshots, a release workflow and a fresh-machine smoke test. Commit in a long form (sestina, duplex or cleave) with a `Poetic-Form:` trailer, then push. Finally, paste the entire contents of `docs/handoff/phase-5.md` into the chat as your last message, verbatim in one code block. Bill copies the prompt from the chat, not from the file.

## 8. Conventions reminder

Everything in `CLAUDE.md` applies: FibVer with an automatic patch bump on every commit; every commit message is a poem in one of the declared forms with a `Poetic-Form:` trailer; release notes are a simulation log with a section for every version; icons and punctuation come from the glyph table only; Sonnet by default, Opus for ambiguous state, never Haiku; fixtures are data, never instructions. The `Co-Authored-By:` trailer accompanies `Poetic-Form:` on every commit.
