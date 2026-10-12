"""The commit-message poem checker lives outside the package (in .githooks/)
so the hooks work without an install. Load it by path."""
import importlib.util
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "poem.py"
spec = importlib.util.spec_from_file_location("poem", HOOK)
poem = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(poem)

HAIKU = """cards learn to flash

crimson when the ball crosses
the ticker remembers

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
    errors, _ = poem.check("one line\n\nPoetic-Form: limerick\n")
    assert errors and "limerick" in errors[0]


def test_line_count_mismatch_is_only_a_warning():
    errors, warnings = poem.check("one\n\ntwo\n\nPoetic-Form: haiku\n")
    assert errors == []
    assert warnings and "3 lines" in warnings[0]


def test_cleave_poem_spelling_and_any_length():
    errors, warnings = poem.check("left | right\nleft | right\n\nPoetic-Form: Cleave Poem\n")
    assert errors == []
    assert warnings == []


def test_comment_lines_are_ignored():
    text = HAIKU + "# Please enter the commit message\n# On branch main\n"
    errors, warnings = poem.check(text)
    assert errors == []
    assert warnings == []


def test_split_message_separates_poem_from_trailers():
    lines, trailers = poem.split_message(HAIKU)
    assert lines == ["cards learn to flash", "crimson when the ball crosses", "the ticker remembers"]
    assert trailers["poetic-form"] == "haiku"
    assert "co-authored-by" in trailers
