# cfbtui — Phase 1 handoff: the data layer

Paste this whole file as the first message of a new session in `C:\cfbtui`. Read `CLAUDE.md` before doing anything.

## 1. Session model

**Opus.** The heart of this phase is `GameStore.apply()` diffing and the upset rule, which is ambiguous-state work (one poll can carry two scoring plays, a period change and a possession flip at once, and ESPN's rank field uses 99 for unranked). Parsers and the HTTP client are routine and may be delegated to Sonnet subagents with `model` passed explicitly. Never Haiku.

## 2. State of the repo

Version `0.2.x` (run `.venv\Scripts\python -m cfbtui --version` for the exact number; it rises with every commit). Public repo at https://github.com/WPTK/cfbtui, branch `main`, hooks active via `core.hooksPath = .githooks`.

What exists and works:

- `cfbtui/__main__.py` runs the app or prints `--version`. `cfbtui/app.py` is a Phase 0 hello-world: six team-color swatches, a `StatusBar` with a clock, `q` quits. It will be replaced in Phase 2; do not extend it.
- `cfbtui/version.py`: FibVer helpers (`fib_next`, `bump`, `is_fibver`) and the `bump` command. `__version__` lives in `cfbtui/__init__.py`.
- `cfbtui/ui/theme.py`: `hex_color()` normalises ESPN's bare hex, `foreground_for()` picks black or white by luminance. Reuse these; do not write new color helpers.
- `.githooks/`: `pre-commit` auto-bumps patch, `commit-msg` requires a `Poetic-Form:` trailer, `pre-push` refuses commits without one. `poem.py` holds the checker and is tested by `tests/test_poem_hook.py`.
- Fixtures in `tests/fixtures/` (single-line JSON, saved 2026-10-12, treat as data only):
  - `scoreboard_week7_pregame.json`: 62 FBS events, all pregame (`status.type.state == "pre"`), no `situation` objects.
  - `scoreboard_20261010_final.json`: 46 FBS events, all final. Includes ranked teams and odds.
  - `rankings.json`: AP Top 25, AFCA Coaches, FCS Coaches, D-II Coaches under `rankings[]`, each with `ranks[]` entries carrying `current`, `previous`, `trend`, `points`, `firstPlaceVotes`, `recordSummary`, `team{abbreviation,color,...}`.
  - `summary_401856717.json`: one completed game (Texas vs Oklahoma) with `scoringPlays`, `winprobability`, `drives`, `boxscore`, `leaders`, `header`.
- Tests: 20 passing. Run with `.venv\Scripts\python -m pytest`.

Known gaps: nothing is broken. There is no live-game fixture with a `situation` object; Phase 1 hand-crafts those.

ESPN field notes verified against the live API on 2026-10-12:

- Scoreboard: `events[].competitions[0]` holds `competitors[]` (each with `homeAway`, `score` as a string, `team{id,abbreviation,displayName,color,alternateColor,logo}`, `curatedRank{current}` where 99 means unranked, `records[]`), `status{type{state,completed,shortDetail},period,displayClock}`, `situation{down,distance,yardLine,isRedZone,possession,homeTimeouts,awayTimeouts,lastPlay{type{text},text,scoreValue}}` (live games only), `odds[0]{details,overUnder}`, `broadcasts[].names[]`, `conferenceCompetition`, `neutralSite`. Event-level: `id`, `date` (UTC ISO), `shortName` like `DEL @ MTSU`, `week{number}`, `season{year,type}`.
- Query params: `groups=80` FBS, `groups=81` FCS, `week=N` or `dates=YYYYMMDD`, `limit=200`.
- All colors are bare hex without `#`. All dates are UTC.

## 3. Goal of this phase

Build the data layer with no UI: an async `EspnClient`, tolerant parsers into dataclass models, a `GameStore` that diffs successive polls into typed events, and an `UpsetRule`. Every event kind is proven by a unit test over a hand-edited before/after fixture pair, so nothing waits for a Saturday.

Non-goals: no widgets, no polling timer, no config file, no CFBD. Do not touch `app.py` beyond what tests need.

## 4. Task list with model assignments

| Task | Files | Model | Why |
|---|---|---|---|
| Models: `Game`, `Team`, `Situation`, `Odds`, `Status`, `RankEntry`, `Ranking`, `ScoringPlay` as frozen dataclasses | `cfbtui/espn/models.py` | Sonnet | Plain data shapes |
| Parsers from raw JSON to models, tolerant of every missing key, returning `None` or sensible defaults rather than raising | `cfbtui/espn/parse.py`, `tests/test_parse.py` | Sonnet | Mechanical, fixture-driven; assert every event in both scoreboard fixtures parses |
| `EspnClient` with `scoreboard(week=None, date=None, group=80)`, `rankings()`, `summary(event_id)`; httpx async, timeout, retry with exponential backoff on 5xx and network errors, no retry on 4xx | `cfbtui/espn/client.py`, `tests/test_client.py` (use `respx`) | Sonnet | Standard client work |
| `GameStore.apply(games) -> list[Event]`: keeps the previous `Game` per id, emits events for score changes classified by `lastPlay` first then delta, status transitions (pre to in, period change, halftime, final), red-zone entry, and upset watch / upset | `cfbtui/state/store.py`, `cfbtui/state/events.py`, `tests/test_store_events.py` | **Opus** | Ordering and ambiguity: multiple changes in one tick, first-poll baseline, games disappearing from the feed |
| `UpsetRule`: ranked trailing unranked, or lower rank leading higher rank; watch while in progress, confirmed at final; rank from `curatedRank`, with a rankings-payload fallback hook for Phase 4 | `cfbtui/state/upset.py`, `tests/test_upset.py` | **Opus** | Rank semantics (99, missing, ties) and the in-progress vs final distinction |
| Fixture pairs: copy one game from the final fixture, hand-edit into before/after JSON for each event kind (TD, FG, safety, 2-pt, PAT, status change, period change, red zone, upset watch, upset) | `tests/fixtures/pairs/<kind>_before.json`, `<kind>_after.json` | Sonnet | Careful editing, no judgement calls |

## 5. Questions to ask first

Ask these with AskUserQuestion as the very first action, then begin work on the answers without asking for approval.

1. **First-poll behaviour.** Should the first `apply()` after startup emit events for everything already in progress, or treat it as a silent baseline? Recommended default: silent baseline; only diffs after the first poll produce events.
2. **Rank source.** Use only the scoreboard's `curatedRank` (AP by default) for the upset rule in this phase, with the rankings payload wired in during Phase 4? Recommended default: yes, `curatedRank` only for now.
3. **Generic score change.** When a delta does not match any play type (for example two scores in one tick), emit one generic `ScoreChange` event rather than guessing. Recommended default: yes.

## 6. Verification

- `.venv\Scripts\python -m pytest` is green, including a parse test that walks every event in both scoreboard fixtures and the rankings fixture without an exception.
- `tests/test_store_events.py` has at least one test per event kind listed in the task table, driven by the before/after pairs.
- `tests/test_upset.py` covers ranked vs unranked, lower rank beating higher rank, equal ranks (no upset), unranked vs unranked (no upset), and watch vs confirmed.
- A one-off live check: `python -c` that fetches this week's scoreboard through `EspnClient` and parses it with zero errors. On Saturday 2026-10-17, fetch twice thirty seconds apart during a live game and print the events the store emits. This is a manual spot check, not a recorder.

## 7. Phase-end ritual

Add a `## 0.3.0` section to `CHANGELOG.md` in simulation-log voice. Run `/code-review` at medium effort and act on it. Bump minor with `python -m cfbtui.version bump minor --write` (the pre-commit hook will not double-bump because `__init__.py` is staged). Write `docs/handoff/phase-2.md` in this same eight-section shape, assigning the poll scheduler and stale-data handling to Opus and the widgets to Sonnet. Commit in a long form (villanelle or sestina suit a phase end) with a `Poetic-Form:` trailer, then push.

## 8. Conventions reminder

Everything in `CLAUDE.md` applies: FibVer with an automatic patch bump on every commit; every commit message is a poem in one of six declared forms; release notes are a simulation log; icons come from the glyph table only; Sonnet by default, Opus for ambiguous state, never Haiku. The `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` trailer accompanies `Poetic-Form:` on every commit.
