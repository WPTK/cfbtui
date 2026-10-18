"""Parser tests against saved ESPN payloads plus hand-written edge cases."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cfbtui.espn.models import GameInfo, GameState, Odds, Situation, Status
from cfbtui.espn.parse import (
    parse_date,
    parse_event,
    parse_int,
    parse_odds,
    parse_rank,
    parse_rankings,
    parse_scoreboard,
    parse_situation,
    parse_status,
    parse_summary,
    parse_team,
)
from cfbtui.ui import theme

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def pregame_payload() -> dict:
    return _load("scoreboard_week7_pregame.json")


@pytest.fixture(scope="module")
def final_payload() -> dict:
    return _load("scoreboard_20261010_final.json")


@pytest.fixture(scope="module")
def pregame(pregame_payload):
    return parse_scoreboard(pregame_payload)


@pytest.fixture(scope="module")
def final(final_payload):
    return parse_scoreboard(final_payload)


@pytest.fixture(scope="module")
def rankings():
    return parse_rankings(_load("rankings.json"))


@pytest.fixture(scope="module")
def summary():
    return parse_summary(_load("summary_401856717.json"))


# ------------------------------------------------------------------ scoreboard


def test_every_event_parses(pregame_payload, final_payload, pregame, final):
    assert len(pregame_payload["events"]) == 62
    assert len(final_payload["events"]) == 46
    assert all(parse_event(e) is not None for e in pregame_payload["events"])
    assert all(parse_event(e) is not None for e in final_payload["events"])
    assert len(pregame.games) == 62
    assert len(final.games) == 46


def test_scoreboard_week_and_season(pregame, final):
    assert pregame.week == 7
    assert final.week == 6
    assert pregame.season_year == 2026
    assert final.season_year == 2026


def test_season_year_falls_back_to_event():
    payload = {
        "events": [
            {
                "id": "1",
                "season": {"year": 2025, "type": 2},
                "competitions": [
                    {"competitors": [{"homeAway": "home", "team": {"id": "1"}}, {"homeAway": "away", "team": {"id": "2"}}]}
                ],
            }
        ]
    }
    board = parse_scoreboard(payload)
    assert board.season_year == 2025
    assert board.week is None


def test_pregame_fixture(pregame):
    assert all(g.is_pregame for g in pregame.games)
    assert all(g.situation is None for g in pregame.games)
    assert sum(1 for g in pregame.games if g.odds is not None) == 59
    assert all(g.home.score == 0 and g.away.score == 0 for g in pregame.games)
    with_odds = next(g for g in pregame.games if g.odds is not None)
    assert with_odds.odds.provider
    assert with_odds.odds.over_under is not None


def test_final_fixture(final):
    assert all(g.is_final for g in final.games)
    assert sum(1 for g in final.games if g.headline) == 44


def test_texas_oklahoma(final):
    game = final.get("401856717")
    assert game is not None
    assert game.away.abbreviation == "TEX"
    assert game.away.score == 24
    assert game.away.rank == 1
    assert game.away.record == "4-1"
    assert game.away.winner is False
    assert game.home.abbreviation == "OU"
    assert game.home.score == 27
    assert game.home.rank is None
    assert game.home.winner is True
    assert game.headline is not None and game.headline.startswith("Oklahoma upsets")
    assert game.leader is not None and game.leader.abbreviation == "OU"
    assert game.neutral_site is True
    assert game.conference_game is True
    assert game.broadcasts == ("ABC",)
    assert game.venue == "Cotton Bowl"
    assert game.date == datetime(2026, 10, 10, 19, 30, tzinfo=UTC)
    assert game.week == 6
    assert game.season_year == 2026
    assert game.season_type == 2
    assert game.status.state == GameState.POST
    assert game.status.completed is True
    assert game.status.name == "STATUS_FINAL"


def test_team_colors_normalised(final, final_payload):
    game = final.get("401856717")
    raw = next(e for e in final_payload["events"] if e["id"] == "401856717")
    raw_color = raw["competitions"][0]["competitors"][1]["team"]["color"]
    assert game.away.team.color == theme.hex_color(raw_color)
    assert game.away.team.color.startswith("#") and len(game.away.team.color) == 7
    assert game.away.team.color == game.away.team.color.lower()
    assert game.home.team.color == "#990000"


def test_broadcasts_deduped_and_flattened():
    event = _two_team_event()
    event["competitions"][0]["broadcasts"] = [
        {"names": ["ESPN", "ESPN2"]},
        {"names": ["ESPN", "ABC"]},
        {"names": None},
        "junk",
    ]
    game = parse_event(event)
    assert game is not None
    assert game.broadcasts == ("ESPN", "ESPN2", "ABC")


# ------------------------------------------------------------------ primitives


def test_parse_date():
    parsed = parse_date("2026-10-10T19:30Z")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed == datetime(2026, 10, 10, 19, 30, tzinfo=UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    assert parse_date("junk") == epoch
    assert parse_date(None) == epoch
    assert parse_date("") == epoch


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, 1), ("7", 7), (99, None), (0, None), (None, None), ("x", None), ("99", None), (25.0, 25), (True, None)],
)
def test_parse_rank(value, expected):
    assert parse_rank(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("27", 27), (27, 27), (27.0, 27), (None, 0), ("", 0), ("x", 0), ({}, 0)],
)
def test_parse_int(value, expected):
    assert parse_int(value) == expected


def test_parse_int_default():
    assert parse_int(None, default=-1) == -1


# ------------------------------------------------------------ situation / etc.


def test_parse_situation_full():
    raw = {
        "down": 3,
        "distance": 7,
        "yardLine": 34,
        "isRedZone": True,
        "possession": "251",
        "homeTimeouts": 2,
        "awayTimeouts": 3,
        "downDistanceText": "3rd & 7 at OU 34",
        "possessionText": "TEX ball",
        "lastPlay": {
            "text": "Arch Manning pass complete",
            "type": {"id": "24", "text": "Pass Reception"},
            "scoreValue": 6,
            "team": {"id": "251"},
        },
    }
    sit = parse_situation(raw)
    assert isinstance(sit, Situation)
    assert (sit.down, sit.distance, sit.yard_line) == (3, 7, 34)
    assert sit.is_red_zone is True
    assert sit.possession == "251"
    assert (sit.home_timeouts, sit.away_timeouts) == (2, 3)
    assert sit.down_distance_text == "3rd & 7 at OU 34"
    assert sit.possession_text == "TEX ball"
    assert sit.last_play is not None
    assert sit.last_play.text == "Arch Manning pass complete"
    assert sit.last_play.type_text == "Pass Reception"
    assert sit.last_play.type_id == "24"
    assert sit.last_play.score_value == 6
    assert sit.last_play.team_id == "251"


def test_parse_situation_empty_and_none():
    assert parse_situation(None) is None
    sit = parse_situation({})
    assert sit is not None
    assert sit.is_red_zone is False
    assert sit.last_play is None
    assert sit.down is None and sit.possession is None


def test_parse_odds_variants():
    entry = {"details": "OU -3.5", "overUnder": 51, "spread": 3.5, "provider": {"name": "DraftKings"}}
    expected = Odds(details="OU -3.5", over_under=51.0, spread=3.5, provider="DraftKings")
    assert parse_odds([entry]) == expected
    assert parse_odds(entry) == expected
    assert parse_odds([]) is None
    assert parse_odds(None) is None
    assert parse_odds({"overUnder": "n/a"}) == Odds()


def test_parse_status_defaults_and_unknown_state():
    assert parse_status(None) == Status()
    assert parse_status({}) == Status()
    weird = parse_status({"type": {"state": "wat", "name": "STATUS_WEIRD"}, "period": "3"})
    assert weird.state == GameState.PRE
    assert weird.name == "STATUS_WEIRD"
    assert weird.period == 3
    live = parse_status(
        {"period": 5, "displayClock": "1:02", "type": {"state": "in", "name": "STATUS_IN_PROGRESS", "completed": False}}
    )
    assert live.state == GameState.IN
    assert live.is_overtime
    assert live.clock == "1:02"


def test_parse_team_defaults():
    team = parse_team({})
    assert team.id == ""
    assert team.color == theme.FALLBACK
    assert team.alt_color == theme.FALLBACK
    assert team.logo is None
    assert parse_team({"id": 5, "color": "abc"}).color == "#aabbcc"


# ---------------------------------------------------------------------- events


def _two_team_event() -> dict:
    return {
        "id": "42",
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "team": {"id": "1"}},
                    {"homeAway": "away", "team": {"id": "2"}},
                ]
            }
        ],
    }


def test_parse_event_rejects_unusable():
    assert parse_event({}) is None
    assert parse_event({"id": "1", "competitions": [{"competitors": [{"homeAway": "home", "team": {"id": "1"}}]}]}) is None
    assert parse_event({"competitions": _two_team_event()["competitions"]}) is None
    two_homes = {
        "id": "1",
        "competitions": [{"competitors": [{"homeAway": "home", "team": {}}, {"homeAway": "home", "team": {}}]}],
    }
    assert parse_event(two_homes) is None
    assert parse_event({"id": "1", "competitions": "nope"}) is None
    assert parse_event("junk") is None  # type: ignore[arg-type]


def test_parse_event_minimal_defaults():
    game = parse_event(_two_team_event())
    assert game is not None
    assert game.id == "42"
    assert game.status.state == GameState.PRE
    assert game.status.period == 0
    assert game.home.score == 0 and game.away.score == 0
    assert game.home.rank is None
    assert game.home.team.color == theme.FALLBACK
    assert game.situation is None
    assert game.odds is None
    assert game.broadcasts == ()
    assert game.venue is None
    assert game.headline is None
    assert game.conference_game is False
    assert game.neutral_site is False
    assert game.week is None
    assert game.date == datetime(1970, 1, 1, tzinfo=UTC)
    assert game.is_pregame and game.leader is None


def test_parse_event_wrong_types_do_not_raise():
    event = _two_team_event()
    comp = event["competitions"][0]
    comp["status"] = "oops"
    comp["odds"] = "oops"
    comp["broadcasts"] = 5
    comp["venue"] = []
    comp["headlines"] = {}
    comp["situation"] = []
    event["week"] = "x"
    event["season"] = None
    game = parse_event(event)
    assert game is not None
    assert game.status == Status()
    assert game.odds is None
    assert game.situation is None


# -------------------------------------------------------------------- rankings


def test_rankings_fixture(rankings):
    assert len(rankings) == 4
    assert [r.type for r in rankings] == ["ap", "usa", "fcs", "afca"]
    ap = next(r for r in rankings if r.type == "ap")
    assert ap.name == "AP Top 25"
    assert ap.short_name == "AP Poll"
    assert ap.week == 7
    assert ap.season_year == 2026
    assert len(ap.ranks) == 25
    first = ap.ranks[0]
    assert first.rank == 1
    assert first.team_id == "61"
    assert first.abbreviation == "UGA"
    assert first.name == "Georgia"
    assert first.previous == 2
    assert first.trend == "+1"
    assert first.points == 1745.0
    assert first.first_place_votes == 66
    assert first.color == "#ba0c2f"
    assert ap.rank_of("61") == 1
    assert ap.rank_of("nope") is None
    assert ap.entry_for("nope") is None


def test_rankings_others_are_unranked(rankings):
    ap = next(r for r in rankings if r.type == "ap")
    assert ap.others
    assert all(e.rank is None for e in ap.others)
    assert all(e.trend for e in ap.others)
    assert all(e.rank is None for e in ap.dropped_out)
    other = ap.others[0]
    assert ap.entry_for(other.team_id) == other


def test_rankings_junk():
    assert parse_rankings({}) == ()
    assert parse_rankings({"rankings": "x"}) == ()
    polls = parse_rankings({"rankings": [{"type": "ap", "ranks": [{"current": 1}, {"current": 2, "team": {"id": 9}}]}]})
    assert len(polls) == 1
    assert len(polls[0].ranks) == 1  # the entry without a team id is dropped
    assert polls[0].ranks[0].name == ""


# --------------------------------------------------------------------- summary


def test_summary_fixture(summary):
    assert summary.game_id == "401856717"
    assert len(summary.scoring_plays) == 9
    first = summary.scoring_plays[0]
    assert first.team_abbreviation == "TEX"
    assert first.team_id == "251"
    assert first.period == 1
    assert first.clock == "6:56"
    assert first.scoring_type == "touchdown"
    assert first.type_text == "Passing Touchdown"
    assert first.away_score == 7
    assert first.home_score == 0
    assert summary.scoring_plays[-1].home_score == 27
    assert summary.home_win_probability == 1.0
    assert summary.status.completed is True
    assert summary.status.state == GameState.POST


def test_summary_junk():
    empty = parse_summary({})
    assert empty.game_id == ""
    assert empty.scoring_plays == ()
    assert empty.home_win_probability is None
    assert empty.status == Status()
    assert parse_summary({"winprobability": [], "scoringPlays": "x"}).home_win_probability is None


def _summary_fixture(name: str):
    return parse_summary(_load(name))


def test_summary_team_stats(summary):
    away, home = summary.team_stats
    assert (away.team_id, home.team_id) == ("251", "201")
    assert [s.name for s in away.stats] == [
        "firstDowns",
        "thirdDownEff",
        "fourthDownEff",
        "totalYards",
        "netPassingYards",
        "yardsPerPass",
        "rushingYards",
        "yardsPerRushAttempt",
        "totalPenaltiesYards",
        "turnovers",
        "possessionTime",
    ]
    third = away.stats[1]
    assert (third.label, third.display_value) == ("3rd down efficiency", "3-14")
    assert {s.name: s.display_value for s in home.stats}["possessionTime"] == "30:31"


def test_summary_leaders(summary):
    assert len(summary.leaders) == 10
    first = summary.leaders[0]
    assert first.category == "Passing Yards"
    assert first.athlete == "John Mateer"
    assert first.stat_line == "18/26, 155 YDS"
    assert first.team_id == "201"
    assert {leader.team_id for leader in summary.leaders} == {"201", "251"}


def test_summary_win_probability_series(summary):
    assert len(summary.winprobability) == 191
    assert summary.winprobability[:2] == (0.1507, 0.147)
    assert summary.winprobability[-1] == summary.home_win_probability == 1.0


def test_summary_drives(summary):
    assert len(summary.drives) == 29
    first = summary.drives[0]
    assert (first.team_id, first.team_abbreviation, first.result) == ("201", "OU", "Punt")
    assert (first.plays, first.yards, first.time) == (3, -2, "1:56")
    assert first.description == "3 plays, -2 yards, 1:56"
    assert not any(d.in_progress for d in summary.drives)


def test_summary_current_drive_is_flagged_and_last():
    payload = {
        "drives": {
            "previous": [{"id": "1", "displayResult": "Punt"}, {"id": "2", "result": "TD"}],
            "current": {"id": "3", "team": {"id": "9", "abbreviation": "XYZ"}, "offensivePlays": 2},
        }
    }
    drives = parse_summary(payload).drives
    assert [d.result for d in drives] == ["Punt", "TD", ""]
    assert [d.in_progress for d in drives] == [False, False, True]
    assert (drives[-1].team_abbreviation, drives[-1].plays) == ("XYZ", 2)
    # A current drive ESPN also lists under previous is not shown twice.
    dup = {"drives": {"previous": [{"id": "3"}], "current": {"id": "3"}}}
    assert [d.in_progress for d in parse_summary(dup).drives] == [True]


def test_summary_game_info_odds_broadcasts_and_recap(summary):
    assert summary.game_info == GameInfo(
        venue="Cotton Bowl", city="Dallas", state="TX", grass=True, attendance=92100
    )
    assert summary.odds == Odds(details="TEX -7.5", over_under=40.5, spread=7.5, provider="DraftKings")
    assert summary.broadcasts == ("ABC",)
    assert summary.recap_headline.startswith("Oklahoma upsets No. 1 Texas")
    assert summary.recap_description.startswith("— Oklahoma and coach Brent Venables")


def test_summary_linescores(summary):
    assert summary.away_linescores == (7, 10, 0, 7)
    assert summary.home_linescores == (0, 7, 3, 17)
    assert sum(summary.away_linescores) == summary.scoring_plays[-1].away_score
    assert sum(summary.home_linescores) == summary.scoring_plays[-1].home_score


def test_summary_fcs_final_has_a_different_broadcast_shape():
    fcs = _summary_fixture("summary_401866668_fcs_final.json")
    assert fcs.broadcasts == ("FloSports",)
    assert fcs.odds.spread == -18.5
    assert fcs.recap_headline is None
    assert fcs.recap_description is None
    assert len(fcs.winprobability) == 163
    assert fcs.home_linescores == (10, 14, 3, 0)


def test_summary_pregame_omits_in_game_sections():
    pre = _summary_fixture("summary_401856835_pregame.json")
    assert pre.team_stats == ()  # only season averages are sent before kickoff
    assert pre.winprobability == ()
    assert pre.home_win_probability is None
    assert pre.drives == ()
    assert pre.away_linescores == pre.home_linescores == ()
    assert pre.broadcasts == ()
    assert pre.recap_headline is None
    assert pre.game_info == GameInfo(
        venue="Acrisure Bounce House", city="Orlando", state="FL", grass=True
    )
    assert pre.odds.details == "BYU -7.5"


def test_summary_fcs_pregame_omits_odds():
    pre = _summary_fixture("summary_401866670_fcs_pregame.json")
    assert pre.odds is None
    assert pre.team_stats == ()
    assert pre.broadcasts == ("FloSports",)
    assert pre.game_info.attendance is None


def test_summary_new_fields_default_on_empty_and_junk():
    for payload in ({}, {"boxscore": "x", "leaders": 3, "drives": [], "gameInfo": "x", "pickcenter": {}}):
        s = parse_summary(payload)
        assert s.team_stats == s.leaders == s.winprobability == s.drives == ()
        assert s.broadcasts == s.away_linescores == s.home_linescores == ()
        assert s.game_info is None or s.game_info == GameInfo()
        assert s.odds is None or s.odds == Odds()
        assert s.recap_headline is None and s.recap_description is None
    junk = {
        "boxscore": {"teams": [{"statistics": "x"}, 5, {"statistics": [{"name": ["firstDowns"]}]}]},
        "leaders": [{"leaders": [{"leaders": []}, {}]}],
        "winprobability": [{"homeWinPercentage": "n/a"}, {"homeWinPercentage": "0.5"}],
        "header": {"competitions": [{"competitors": [{"homeAway": "home", "linescores": [{}, 3]}]}]},
    }
    s = parse_summary(junk)
    assert s.team_stats == () and s.leaders == ()
    assert s.winprobability == (0.5,)
    assert s.home_linescores == ()


def test_overall_record_never_falls_back_to_a_split():
    from cfbtui.espn.parse import parse_competitor

    raw = {"homeAway": "home", "team": {"id": "1"}, "records": [{"name": "Home", "type": "home", "summary": "2-0"}]}
    assert parse_competitor(raw).record is None
    raw["records"].append({"name": "overall", "type": "total", "summary": "4-1"})
    assert parse_competitor(raw).record == "4-1"


def test_scoreboard_week_falls_back_to_the_events():
    from cfbtui.espn.parse import parse_scoreboard

    payload = {
        "events": [
            {
                "id": "1",
                "week": {"number": 9},
                "competitions": [{"competitors": [{"homeAway": "home", "team": {"id": "1"}}, {"homeAway": "away", "team": {"id": "2"}}]}],
            }
        ]
    }
    assert parse_scoreboard(payload).week == 9
