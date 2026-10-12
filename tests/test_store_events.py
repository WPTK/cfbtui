"""GameStore diffs, driven by the hand-edited before/after pairs in fixtures/pairs."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cfbtui.espn.models import Game, GameState, LastPlay, Status
from cfbtui.espn.parse import parse_scoreboard
from cfbtui.state.events import (
    GameFinal,
    GameStarted,
    Halftime,
    PeriodChanged,
    RedZone,
    ScoreCorrected,
    Scored,
    ScoreKind,
    StatusChanged,
    Upset,
    UpsetWatch,
)
from cfbtui.state.store import GameStore, decompose, kind_from_play

PAIRS = Path(__file__).parent / "fixtures" / "pairs"


def load(name: str) -> Game:
    payload = json.loads((PAIRS / f"{name}.json").read_text(encoding="utf-8"))
    board = parse_scoreboard(payload)
    assert len(board.games) == 1, name
    return board.games[0]


def pair(kind: str) -> tuple[Game, Game]:
    return load(f"{kind}_before"), load(f"{kind}_after")


def diff(kind: str, store: GameStore | None = None):
    """Apply before (silently) then after; return after's events."""
    before, after = pair(kind)
    store = store or GameStore()
    store.apply([before])
    return store.apply([after])


def kinds(events) -> list[str]:
    return [e.kind for e in events]


# --- scoring ----------------------------------------------------------------


def test_touchdown_from_last_play():
    events = diff("touchdown")
    assert kinds(events) == ["scored"]
    ev = events[0]
    assert isinstance(ev, Scored)
    assert ev.score_kind is ScoreKind.TOUCHDOWN
    assert ev.points == 7
    assert ev.team.abbreviation == "TEX"
    assert not ev.inferred
    assert "Wingo" in ev.text
    assert ev.away_score == 14 and ev.home_score == 7
    assert str(ev).startswith("TD TEX +7 [TEX VS OU] TEX 14 OU 7")


def test_field_goal_from_last_play():
    events = diff("field_goal")
    assert kinds(events) == ["scored"]
    ev = events[0]
    assert ev.score_kind is ScoreKind.FIELD_GOAL and ev.points == 3
    assert ev.team.abbreviation == "TEX" and not ev.inferred


def test_safety_from_last_play():
    events = diff("safety")
    assert kinds(events) == ["scored"]
    ev = events[0]
    assert ev.score_kind is ScoreKind.SAFETY and ev.points == 2
    assert ev.team.abbreviation == "OU" and not ev.inferred


def test_two_point_from_last_play():
    events = diff("two_point")
    assert kinds(events) == ["scored"]
    ev = events[0]
    assert ev.score_kind is ScoreKind.TWO_POINT and ev.points == 2
    assert ev.team.abbreviation == "OU" and not ev.inferred


def test_pat_from_last_play():
    events = diff("pat")
    assert kinds(events) == ["scored"]
    ev = events[0]
    assert ev.score_kind is ScoreKind.PAT and ev.points == 1
    assert ev.team.abbreviation == "TEX" and not ev.inferred


def test_six_point_touchdown_then_bare_two_is_a_conversion():
    """TD for 6 in one tick, +2 with no lastPlay in the next: a two-point try, not a safety."""
    before, after = pair("two_point")
    prior = replace(before, home=replace(before.home, score=9))  # same red-zone situation, 6 fewer points
    after = replace(after, situation=None)
    store = GameStore()
    store.apply([prior])
    first = store.apply([before])
    assert kinds(first) == ["scored"]
    assert first[0].score_kind is ScoreKind.TOUCHDOWN and first[0].points == 6 and not first[0].inferred
    second = store.apply([after])
    assert kinds(second) == ["scored"]
    assert second[0].score_kind is ScoreKind.TWO_POINT and second[0].inferred


def test_bare_two_without_pending_touchdown_is_a_safety():
    before, after = pair("two_point")
    after = replace(after, situation=None)
    store = GameStore()
    store.apply([before])  # first sight: the 6-point TD is already on the board, no delta
    events = store.apply([after])
    assert kinds(events) == ["scored"]
    assert events[0].score_kind is ScoreKind.SAFETY and events[0].inferred


def test_bare_one_is_a_pat():
    before, after = pair("pat")
    after = replace(after, situation=None)
    events = diff_with(before, after)
    assert kinds(events) == ["scored"]
    assert events[0].score_kind is ScoreKind.PAT and events[0].inferred


def diff_with(before: Game, after: Game):
    store = GameStore()
    store.apply([before])
    return store.apply([after])


def test_multi_score_is_decomposed_when_last_play_does_not_explain_it():
    events = diff("multi_score")
    assert kinds(events) == ["scored", "scored"]
    td, fg = events
    assert td.score_kind is ScoreKind.TOUCHDOWN and td.points == 7 and td.inferred
    assert fg.score_kind is ScoreKind.FIELD_GOAL and fg.points == 3 and fg.inferred
    assert td.team.abbreviation == fg.team.abbreviation == "TEX"
    assert td.text == "" and "TD? TEX +7" in str(td)


def test_score_correction_is_not_a_score():
    events = diff("score_correction")
    assert kinds(events) == ["score_corrected"]
    ev = events[0]
    assert isinstance(ev, ScoreCorrected)
    assert ev.team.abbreviation == "TEX" and ev.before == 20 and ev.after == 17


def test_both_teams_score_in_one_tick_last_play_side_goes_last():
    before, after = pair("upset_watch")  # 17-17 -> OU pick-six 24-17
    after = replace(after, away=replace(after.away, score=24))  # TEX also +7, no play to explain it
    events = diff_with(before, after)
    assert kinds(events) == ["scored", "scored"]
    tex, ou = events
    assert tex.team.abbreviation == "TEX" and tex.inferred
    assert ou.team.abbreviation == "OU" and not ou.inferred and "Bowen" in ou.text


def test_last_play_for_the_other_team_does_not_explain_a_delta():
    before, after = pair("touchdown")
    play = after.situation.last_play
    after = replace(after, situation=replace(after.situation, last_play=replace(play, team_id="201")))
    events = diff_with(before, after)
    assert kinds(events) == ["scored"]
    assert events[0].inferred and events[0].score_kind is ScoreKind.TOUCHDOWN


# --- status -----------------------------------------------------------------


def test_game_start():
    events = diff("game_start")
    assert kinds(events) == ["game_started"]
    assert isinstance(events[0], GameStarted)
    assert str(events[0]).startswith("KICKOFF [TEX VS OU] TEX 0 OU 0")


def test_period_change():
    events = diff("period_change")
    assert kinds(events) == ["period_changed"]
    assert isinstance(events[0], PeriodChanged) and events[0].period == 2
    assert str(events[0]).startswith("Q2 ")


def test_halftime_and_second_half():
    events = diff("halftime")
    assert kinds(events) == ["halftime"]
    assert isinstance(events[0], Halftime)
    events = diff("second_half")
    assert kinds(events) == ["period_changed"]
    assert events[0].period == 3


def test_overtime_period_label():
    before, after = pair("period_change")
    after = replace(after, status=replace(after.status, period=5))
    events = diff_with(before, after)
    assert kinds(events) == ["period_changed"]
    assert events[0].is_overtime and str(events[0]).startswith("OT1 ")


def test_final_and_upset():
    events = diff("final")
    assert kinds(events) == ["game_final", "upset"]
    final, upset = events
    assert isinstance(final, GameFinal)
    assert final.winner.abbreviation == "OU" and final.loser.abbreviation == "TEX"
    assert not final.is_tie
    assert isinstance(upset, Upset)
    assert upset.underdog.abbreviation == "OU" and upset.favorite.abbreviation == "TEX"
    assert str(upset) == "UPSET OU over #1 TEX [TEX VS OU] TEX 24 OU 27"


def test_final_without_upset_when_favorite_wins():
    before, after = pair("final")
    before = replace(before, away=replace(before.away, score=30))
    after = replace(after, away=replace(after.away, score=30))
    events = diff_with(before, after)
    assert kinds(events) == ["game_final"]


def test_delay_is_a_status_change():
    before, _ = pair("touchdown")
    delayed = replace(before, status=replace(before.status, name="STATUS_DELAYED"))
    events = diff_with(before, delayed)
    assert kinds(events) == ["status_changed"]
    ev = events[0]
    assert isinstance(ev, StatusChanged)
    assert ev.before == "STATUS_IN_PROGRESS" and ev.after == "STATUS_DELAYED"
    # resuming is a change too
    resumed = replace(delayed, status=replace(delayed.status, name="STATUS_IN_PROGRESS"))
    store = GameStore()
    store.apply([delayed])
    assert kinds(store.apply([resumed])) == ["status_changed"]


def test_postponed_before_kickoff_is_not_a_kickoff():
    before, _ = pair("game_start")
    postponed = replace(
        before,
        status=Status(state=GameState.POST, name="STATUS_POSTPONED", completed=False),
    )
    events = diff_with(before, postponed)
    assert kinds(events) == ["status_changed"]


def test_end_period_to_in_progress_is_quiet():
    before, _ = pair("period_change")
    ended = replace(before, status=replace(before.status, name="STATUS_END_PERIOD"))
    assert diff_with(before, ended) == []


def test_outage_from_scheduled_to_final_in_one_tick():
    before = load("game_start_before")
    after = load("final_after")
    events = diff_with(before, after)
    scored = [e for e in events if isinstance(e, Scored)]
    assert kinds(events)[0] == "game_started"
    assert kinds(events)[-2:] == ["game_final", "upset"]
    tex = [(e.points, e.score_kind) for e in scored if e.team.abbreviation == "TEX"]
    ou = [(e.points, e.score_kind) for e in scored if e.team.abbreviation == "OU"]
    assert tex == decompose(24) and ou == decompose(27)
    assert all(e.inferred for e in scored)
    # away side first when no lastPlay says otherwise
    assert scored[0].team.abbreviation == "TEX"


# --- situation --------------------------------------------------------------


def test_red_zone_entry():
    events = diff("red_zone")
    assert kinds(events) == ["red_zone"]
    ev = events[0]
    assert isinstance(ev, RedZone) and ev.team.abbreviation == "OU"
    assert str(ev).startswith("RED ZONE OU at TEX 17")


def test_red_zone_does_not_repeat_while_still_inside():
    before, after = pair("red_zone")
    store = GameStore()
    store.apply([before])
    store.apply([after])
    again = replace(after, situation=replace(after.situation, yard_line=90, possession_text="TEX 10"))
    assert store.apply([again]) == []


def test_red_zone_fires_again_when_possession_flips_inside_it():
    before, after = pair("red_zone")
    store = GameStore()
    store.apply([before])
    store.apply([after])
    flipped = replace(after, situation=replace(after.situation, possession="251"))
    events = store.apply([flipped])
    assert kinds(events) == ["red_zone"] and events[0].team.abbreviation == "TEX"


def test_field_goal_leaves_red_zone_without_an_event():
    """field_goal_before is in the red zone; after is not. Only the score shows."""
    assert kinds(diff("field_goal")) == ["scored"]


# --- upsets -----------------------------------------------------------------


def test_upset_watch_after_pick_six():
    events = diff("upset_watch")
    assert kinds(events) == ["scored", "upset_watch"]
    scored, watch = events
    assert scored.score_kind is ScoreKind.TOUCHDOWN and scored.team.abbreviation == "OU"
    assert isinstance(watch, UpsetWatch)
    assert watch.underdog.abbreviation == "OU" and watch.favorite.abbreviation == "TEX"
    assert str(watch) == "UPSET WATCH OU leads #1 TEX [TEX VS OU] TEX 17 OU 24"


def test_ranked_upset_watch():
    events = diff("ranked_upset_watch")
    assert kinds(events) == ["scored", "upset_watch"]
    watch = events[1]
    assert watch.underdog.rank == 12 and watch.favorite.rank == 5
    assert str(watch).startswith("UPSET WATCH #12 OU leads #5 TEX")


def test_favorite_taking_the_lead_is_not_a_watch():
    events = diff("favorite_leads")
    assert kinds(events) == ["scored"]


def test_upset_watch_does_not_repeat_while_underdog_keeps_leading():
    before, after = pair("upset_watch")
    store = GameStore()
    store.apply([before])
    store.apply([after])
    bigger = replace(after, home=replace(after.home, score=27), situation=None)
    events = store.apply([bigger])
    assert kinds(events) == ["scored"]


def test_upset_watch_fires_again_after_the_lead_changes_hands_twice():
    before, after = pair("upset_watch")  # 17-17 -> OU 24-17
    store = GameStore()
    store.apply([before])
    assert kinds(store.apply([after])) == ["scored", "upset_watch"]
    tex_back = replace(after, away=replace(after.away, score=25), situation=None)  # TEX 25-24 (+8)
    assert kinds(store.apply([tex_back])) == ["scored"]
    ou_again = replace(tex_back, home=replace(tex_back.home, score=31), situation=None)  # OU 31-25 (+7)
    assert kinds(store.apply([ou_again])) == ["scored", "upset_watch"]


def test_upset_from_watch_emits_only_upset_at_final():
    watch_state = load("upset_watch_after")
    final = load("final_after")
    store = GameStore()
    store.apply([watch_state])
    events = store.apply([final])
    assert kinds(events) == ["scored", "scored", "game_final", "upset"]


# --- first sight, vanishing games, reset -------------------------------------


def test_first_sight_of_live_game_describes_it():
    store = GameStore()
    events = store.apply([load("upset_watch_after")])
    assert kinds(events) == ["game_started", "upset_watch"]
    store = GameStore()
    assert kinds(store.apply([load("red_zone_after")])) == ["game_started", "red_zone"]
    store = GameStore()
    assert kinds(store.apply([load("halftime_after")])) == ["game_started", "halftime"]


def test_first_sight_of_pregame_and_final_is_silent():
    assert GameStore().apply([load("game_start_before")]) == []
    assert GameStore().apply([load("final_after")]) == []


def test_first_sight_can_be_silenced():
    store = GameStore(emit_on_first_sight=False)
    assert store.apply([load("upset_watch_after")]) == []


def test_equal_state_is_quiet():
    before, after = pair("touchdown")
    store = GameStore()
    store.apply([before])
    store.apply([after])
    assert store.apply([load("touchdown_after")]) == []  # equal but not identical
    assert store.polls == 3


def test_vanishing_game_is_remembered():
    before, after = pair("touchdown")
    store = GameStore()
    store.apply([before])
    assert store.apply([]) == []
    assert len(store) == 0 and store.games == ()
    assert store.get(before.id) is before  # still known
    events = store.apply([after])
    assert kinds(events) == ["scored"]  # a diff, not a first sight
    assert store.get(after.id) is after and after.id in store


def test_reset_makes_the_next_poll_a_first_sight():
    before, after = pair("upset_watch")
    store = GameStore()
    store.apply([before])
    store.reset()
    assert store.polls == 0
    assert kinds(store.apply([after])) == ["game_started", "upset_watch"]


def test_games_in_feed_order_and_live_view():
    td_before, td_after = pair("touchdown")
    fin_before, fin_after = pair("final")
    other_before = replace(fin_before, id="2")
    other_after = replace(fin_after, id="2")
    store = GameStore()
    store.apply([td_before, other_before])
    events = store.apply([other_after, td_after])
    assert [e.game_id for e in events] == ["2", "2", "401856717"]
    assert [g.id for g in store.games] == ["2", "401856717"]
    assert [g.id for g in store.live] == ["401856717"]


# --- helpers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_text", "text", "points", "expected"),
    [
        ("Passing Touchdown", "X 34 Yd pass from Y (Z Kick)", 7, ScoreKind.TOUCHDOWN),
        ("Rushing Touchdown", "X 2 Yd Run (Two-Point Pass Conversion Good)", 8, ScoreKind.TOUCHDOWN),
        ("Rushing Touchdown", "X 2 Yd Run", 6, ScoreKind.TOUCHDOWN),
        ("Field Goal Good", "X 23 Yd Field Goal", 3, ScoreKind.FIELD_GOAL),
        ("Field Goal Good", "X 23 Yd Field Goal", 7, None),
        ("Safety", "X sacked in end zone for a safety", 2, ScoreKind.SAFETY),
        ("Two-Point Conversion Good", "X pass to Y for Two-Point Conversion", 2, ScoreKind.TWO_POINT),
        ("Extra Point Good", "X Kick", 1, ScoreKind.PAT),
        ("Point After Touchdown", "X Kick", 1, ScoreKind.PAT),
        ("Rush", "X run for 4 yds", 3, None),
        ("Passing Touchdown", "X 34 Yd pass from Y", 3, None),
    ],
)
def test_kind_from_play(type_text, text, points, expected):
    play = LastPlay(text=text, type_text=type_text, score_value=points, team_id="1")
    assert kind_from_play(play, points) is expected


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        (0, []),
        (1, [(1, ScoreKind.PAT)]),
        (2, [(2, ScoreKind.SAFETY)]),
        (3, [(3, ScoreKind.FIELD_GOAL)]),
        (6, [(6, ScoreKind.TOUCHDOWN)]),
        (7, [(7, ScoreKind.TOUCHDOWN)]),
        (8, [(8, ScoreKind.TOUCHDOWN)]),
        (9, [(6, ScoreKind.TOUCHDOWN), (3, ScoreKind.FIELD_GOAL)]),
        (10, [(7, ScoreKind.TOUCHDOWN), (3, ScoreKind.FIELD_GOAL)]),
        (11, [(8, ScoreKind.TOUCHDOWN), (3, ScoreKind.FIELD_GOAL)]),
        (14, [(7, ScoreKind.TOUCHDOWN), (7, ScoreKind.TOUCHDOWN)]),
        (17, [(7, ScoreKind.TOUCHDOWN), (7, ScoreKind.TOUCHDOWN), (3, ScoreKind.FIELD_GOAL)]),
    ],
)
def test_decompose(points, expected):
    assert decompose(points) == expected


def test_decompose_two_with_pending_pat():
    assert decompose(2, pat_pending=True) == [(2, ScoreKind.TWO_POINT)]
    assert decompose(5, pat_pending=True) == [(3, ScoreKind.FIELD_GOAL), (2, ScoreKind.TWO_POINT)]


def test_teamless_last_play_explains_only_a_sole_scorer():
    before, after = pair("upset_watch")  # 17-17 -> OU 24-17 by pick-six
    play = replace(after.situation.last_play, team_id=None)
    after = replace(after, situation=replace(after.situation, last_play=play))
    events = diff_with(before, after)
    assert kinds(events) == ["scored", "upset_watch"]
    assert not events[0].inferred and "Bowen" in events[0].text
    # both sides +7 with the same teamless play: nobody gets to claim it
    both = replace(after, away=replace(after.away, score=24))
    events = diff_with(before, both)
    assert kinds(events) == ["scored", "scored"]
    assert all(e.inferred and e.text == "" for e in events)
