from cfbtui.ui.theme import BLACK, FALLBACK, WHITE, foreground_for, hex_color


def test_hex_color_adds_hash_and_lowercases():
    assert hex_color("461D7C") == "#461d7c"
    assert hex_color("#fdd023") == "#fdd023"


def test_hex_color_expands_short_form():
    assert hex_color("abc") == "#aabbcc"


def test_hex_color_falls_back_on_junk():
    assert hex_color(None) == FALLBACK
    assert hex_color("") == FALLBACK
    assert hex_color("zzzzzz") == FALLBACK
    assert hex_color("12345") == FALLBACK


def test_foreground_for_dark_and_light_backgrounds():
    assert foreground_for("461d7c") == WHITE  # LSU purple
    assert foreground_for("ffcb05") == BLACK  # Michigan maize
    assert foreground_for("ffffff") == BLACK
    assert foreground_for("000000") == WHITE
