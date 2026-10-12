import pytest

from cfbtui.state.events import ScoreKind
from cfbtui.ui import glyphs as g


def test_four_sets_in_documented_order():
    assert g.GLYPH_SET_NAMES == ("ascii", "unicode", "emoji", "nerd")


def test_default_is_nerd():
    assert g.get().name == "nerd"
    assert g.DEFAULT_SET == "nerd"


@pytest.mark.parametrize("name", g.GLYPH_SET_NAMES)
def test_every_field_is_filled_in_every_set(name):
    table = g.get(name)
    for field_name in g.GLYPH_FIELDS:
        assert getattr(table, field_name), f"{name}.{field_name} is empty"


def test_ascii_set_is_pure_ascii():
    table = g.get("ascii")
    for field_name in g.GLYPH_FIELDS:
        assert getattr(table, field_name).isascii(), field_name


def test_get_is_case_insensitive_and_loud_on_junk():
    assert g.get(" Unicode ").name == "unicode"
    with pytest.raises(KeyError, match="choose from"):
        g.get("wingdings")


def test_next_name_cycles_and_wraps():
    seen = [g.GLYPH_SET_NAMES[0]]
    for _ in g.GLYPH_SET_NAMES:
        seen.append(g.next_name(seen[-1]))
    assert seen[-1] == g.GLYPH_SET_NAMES[0]
    assert seen[:-1] == list(g.GLYPH_SET_NAMES)
    assert g.next_name("nonsense") == g.DEFAULT_SET


def test_score_kind_icons():
    table = g.get("ascii")
    assert table.for_score_kind(ScoreKind.TOUCHDOWN) == table.touchdown
    assert table.for_score_kind(ScoreKind.FIELD_GOAL) == table.field_goal
    assert table.for_score_kind(ScoreKind.UNKNOWN) == table.score


def test_timeout_dots():
    table = g.get("ascii")
    assert table.timeouts(3) == "ooo"
    assert table.timeouts(1) == "o.."
    assert table.timeouts(0) == "..."
    assert table.timeouts(9) == "ooo"
    assert table.timeouts(None) == ""
