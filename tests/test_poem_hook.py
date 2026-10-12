"""The commit-message poem checker lives outside the package (in .githooks/)
so the hooks work without an install. Load it by path."""
import importlib.util
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "poem.py"
spec = importlib.util.spec_from_file_location("poem", HOOK)
poem = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(poem)

HAIKU = """cards learn to glow red

crimson when the ball crosses
ticker remembers

Poetic-Form: haiku
Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
"""


def test_valid_haiku_passes():
    errors, warnings = poem.check(HAIKU)
    assert errors == []
    assert warnings == []


def test_missing_trailer_is_an_error():
    errors, _ = poem.check("cards learn to flash\n\ncrimson when the ball crosses\nthe ticker remembers\n")
    assert errors and "Poetic-Form" in errors[0]


def test_unknown_form_is_an_error():
    errors, _ = poem.check("one line\n\nPoetic-Form: ode\n")
    assert errors and "ode" in errors[0]


def test_line_count_mismatch_is_only_a_warning():
    errors, warnings = poem.check("one\n\ntwo\n\nPoetic-Form: haiku\n")
    assert errors == []
    assert warnings and "3 lines" in warnings[0]


def test_cleave_poem_spelling_and_any_length():
    errors, warnings = poem.check("left | right\nleft | right\n\nPoetic-Form: Cleave Poem\n")
    assert errors == []
    assert warnings == []


def test_tanku_alias_is_accepted():
    text = (
        "cards learn to glow red\n\ncrimson when the ball crosses\nticker remembers\n"
        "the band plays on through the rain\nand nobody wants to leave\n\nPoetic-Form: Tanku\n"
    )
    errors, warnings = poem.check(text)
    assert errors == []
    assert warnings == []


def test_blank_line_between_trailers_still_finds_the_form():
    text = "cards learn to glow red\n\ncrimson when the ball crosses\nticker remembers\n\nPoetic-Form: haiku\n\nCo-Authored-By: X <x@y>\n"
    errors, warnings = poem.check(text)
    assert errors == []
    assert warnings == []


def test_poem_lines_with_colons_are_not_trailers():
    text = "halftime: the band plays\n\nscore: nobody remembers\nclock: it runs anyway\n\nPoetic-Form: haiku\n"
    lines, trailers = poem.split_message(text)
    assert len(lines) == 3
    assert list(trailers) == ["poetic-form"]


def test_comment_lines_are_ignored():
    text = HAIKU + "# Please enter the commit message\n# On branch main\n"
    errors, warnings = poem.check(text)
    assert errors == []
    assert warnings == []


def test_split_message_separates_poem_from_trailers():
    lines, trailers = poem.split_message(HAIKU)
    assert lines == ["cards learn to glow red", "crimson when the ball crosses", "ticker remembers"]
    assert trailers["poetic-form"] == "haiku"
    assert "co-authored-by" in trailers


def test_villanelle_is_no_longer_a_form():
    errors, _ = poem.check("one line\n\nPoetic-Form: villanelle\n")
    assert errors and "villanelle" in errors[0]


def test_ending_on_a_dangler_warns():
    text = "cards learn to glow red\n\ncrimson when the ball crosses\nthe ticker remembers the\n\nPoetic-Form: haiku\n"
    _, warnings = poem.check(text)
    assert any("cut off" in w for w in warnings)


def test_syllable_miscount_warns():
    pytest = __import__("pytest")
    pytest.importorskip("pronouncing")
    text = "cards learn to glow red\n\ncrimson when the ball crosses over everything\nthe ticker remembers\n\nPoetic-Form: haiku\n"
    _, warnings = poem.check(text)
    assert any("line 2" in w and "syllables" in w for w in warnings)


def test_good_haiku_has_no_syllable_warning():
    pytest = __import__("pytest")
    pytest.importorskip("pronouncing")
    _, warnings = poem.check(HAIKU)
    assert warnings == []


def test_unknown_word_skips_the_line():
    pytest = __import__("pytest")
    pytest.importorskip("pronouncing")
    assert poem.count_syllables("zzxqv blorp") is None


def _needs_dict():
    __import__("pytest").importorskip("pronouncing")


def test_senryu_uses_haiku_counts():
    _needs_dict()
    errors, warnings = poem.check(HAIKU.replace("haiku", "senryu"))
    assert errors == [] and warnings == []


def test_cinquain_counts():
    _needs_dict()
    text = "the cards\nglow crimson red\nwhen the ball is crossing\nand all the ticker remembers\na score\n\nPoetic-Form: cinquain\n"
    errors, warnings = poem.check(text)
    assert errors == [] and warnings == []


def test_limerick_rhyme_warning():
    _needs_dict()
    good = "a card flashed with joy on the screen\nwhen the touchdown was plainly seen\nthe ticker said so\nand the fans said whoa\nthe finest of days we have seen\n\nPoetic-Form: limerick\n"
    _, w = poem.check(good)
    assert not any("rhyme" in x for x in w)
    bad = good.replace("seen", "tall")
    _, w = poem.check(bad)
    assert any("rhyme" in x for x in w)


def test_couplet_and_clerihew_line_counts():
    _, w = poem.check("one\ntwo\nthree\n\nPoetic-Form: couplet\n")
    assert any("2 lines" in x for x in w)
    _, w = poem.check("one\ntwo\n\nPoetic-Form: clerihew\n")
    assert any("4 lines" in x for x in w)


def test_etheree_has_ten_lines():
    _, w = poem.check("a\n\nPoetic-Form: etheree\n")
    assert any("10 lines" in x for x in w)
