"""Discord text: one Markdown line per game, boards as code blocks under the 2000 character limit."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from cfbtui.espn.models import RankEntry, Ranking
from cfbtui.share import DISCORD_LIMIT, FENCE, escape, format_board, format_game, format_poll
from cfbtui.ui.glyphs import ASCII, UNICODE
from tests.fakes import load_board, load_game

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def test_final_game_is_one_line_with_the_winner_in_bold():
    game = load_game("pairs/final_after.json")
    line = format_game(game, UNICODE, now=NOW)
    assert "\n" not in line
    assert line.count("**") == 2, "only the winner is bold"
    winner = game.leader
    assert f"**{winner.abbreviation}**" in line or f"{winner.abbreviation}**" in line
    assert "Final" in line and "@" in line


def test_live_game_bolds_the_leader_and_shows_the_clock():
    game = load_game("pairs/touchdown_after.json")
    line = format_game(game, UNICODE, now=NOW)
    assert line.count("**") == 2
    assert "Q" in line


def test_pregame_game_has_no_score_and_no_bold():
    game = load_board("scoreboard_week7_pregame.json").games[0]
    line = format_game(game, UNICODE, now=NOW)
    assert "**" not in line
    assert line.startswith(f"{game.away.abbreviation} @ ") or line.startswith("#")
    assert " @ " in line and line.split(" @ ")[0].replace("#", "").split()[-1] == game.away.abbreviation
    assert "ET" in line


def test_tied_game_bolds_nobody():
    game = load_game("pairs/touchdown_before.json")
    tied = replace(game, home=replace(game.home, score=7), away=replace(game.away, score=7))
    assert "**" not in format_game(tied, UNICODE, now=NOW)


def test_markdown_characters_in_text_are_escaped():
    assert escape("a_b*c") == "a\\_b\\*c"
    game = load_game("pairs/final_after.json")
    odd = replace(game, away=replace(game.away, team=replace(game.away.team, abbreviation="A_B")))
    assert "A\\_B" in format_game(odd, UNICODE, now=NOW)


def test_ascii_set_gives_ascii_only_text():
    game = load_game("pairs/final_after.json")
    assert format_game(game, ASCII, now=NOW).isascii()


def test_no_games_means_no_messages():
    assert format_board([], UNICODE) == []


def test_small_board_is_one_code_block_with_a_title():
    games = load_board("scoreboard_week7_pregame.json").games[:4]
    [message] = format_board(games, UNICODE, title="Week 7 FBS", now=NOW)
    assert message.startswith(f"{FENCE}\nWeek 7 FBS\n") and message.endswith(f"\n{FENCE}")
    assert len(message) <= DISCORD_LIMIT
    assert len(message.splitlines()) == len(games) + 3


def test_columns_line_up():
    games = load_board("scoreboard_20261010_final.json").games[:6]
    [message] = format_board(games, UNICODE, now=NOW)
    body = message.splitlines()[1:-1]
    assert len({line.index("@") for line in body}) == 1


def test_a_long_board_splits_between_games_under_the_limit():
    games = list(load_board("scoreboard_week7_pregame.json").games)
    big = [replace(games[i % len(games)], id=str(i)) for i in range(120)]
    messages = format_board(big, UNICODE, title="Week 7 FBS", now=NOW)
    assert len(messages) > 1
    assert all(len(m) <= DISCORD_LIMIT for m in messages)
    assert all(m.startswith(FENCE) and m.endswith(FENCE) for m in messages)
    assert "Week 7 FBS" in messages[0] and all("Week 7 FBS" not in m for m in messages[1:])
    lines = [ln for m in messages for ln in m.splitlines()[1:-1]]
    assert len(lines) == len(big) + 1, "every game appears exactly once, plus the title"


def test_a_tiny_limit_still_never_exceeds_it():
    games = load_board("scoreboard_week7_pregame.json").games[:5]
    messages = format_board(games, UNICODE, now=NOW, limit=120)
    assert messages and all(len(m) <= 120 for m in messages)


def test_a_fence_inside_text_cannot_break_out_of_the_block():
    game = load_game("pairs/final_after.json")
    odd = replace(game, away=replace(game.away, team=replace(game.away.team, abbreviation="A```B")))
    [message] = format_board([odd], UNICODE, now=NOW)
    assert message.count(FENCE) == 2


def test_a_kickoff_more_than_five_days_out_keeps_its_date_without_being_told_the_time():
    game = load_board("scoreboard_week7_pregame.json").games[0]
    far = replace(game, date=datetime.now(UTC).replace(microsecond=0) + __import__("datetime").timedelta(days=14))
    assert any(month in format_game(far, UNICODE) for month in ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))


# --- polls ---------------------------------------------------------------------------


def _poll(count: int = 3) -> Ranking:
    entries = tuple(
        RankEntry(
            team_id=str(i),
            abbreviation=f"T{i}",
            name="Texas" if i == 1 else f"Team {i}",
            color="000000",
            rank=i + 1,
            previous=None if i == 2 else i + 1,
            trend="+2" if i == 1 else "-",
            points=1500.0 - i,
            first_place_votes=5 if i == 0 else 0,
            record="6-0",
        )
        for i in range(count)
    )
    return Ranking(id="1", name="AP Top 25", short_name="AP", type="ap", week=7, ranks=entries)


def test_poll_is_a_code_block_with_aligned_columns_under_a_heading():
    (message,) = format_poll(_poll(), UNICODE)
    assert message.startswith(f"{FENCE}\nAP Top 25  Week 7\n") and message.endswith(f"\n{FENCE}")
    rows = message.splitlines()[2:-1]
    assert rows[0].split() == ["#1", "Team", "0", "(5)", "6-0", "1500"]
    assert rows[1].split() == ["#2", "Texas", "6-0", "1499", "+2"]
    assert rows[2].split() == ["#3", "Team", "2", "6-0", "1498", "new"]
    assert len({row.index("6-0") for row in rows}) == 1, "records line up"
    assert not any(0xE000 <= ord(ch) <= 0xF8FF for ch in message)


def test_poll_splits_between_rows_and_every_message_fits():
    messages = format_poll(_poll(25), UNICODE, limit=300)
    assert len(messages) > 1
    assert all(len(m) <= 300 and m.startswith(FENCE) and m.endswith(FENCE) for m in messages)
    assert "AP Top 25" in messages[0] and "AP Top 25" not in messages[1]
    assert sum(m.count("6-0") for m in messages) == 25


def test_a_full_poll_fits_one_message_and_an_empty_poll_has_none():
    (message,) = format_poll(_poll(25), UNICODE)
    assert len(message) <= DISCORD_LIMIT
    assert format_poll(_poll(0), UNICODE) == []
