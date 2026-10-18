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


def _fixture_colors() -> set[str]:
    import re
    from pathlib import Path

    found: set[str] = set()
    for path in (Path(__file__).parent / "fixtures").rglob("*.json"):
        found.update(re.findall(r'"(?:color|alternateColor)":\s*"([0-9a-fA-F]{6})"', path.read_text(encoding="utf-8")))
    return {hex_color(c) for c in found} | {"#000000", "#ffffff", "#ffff00", "#001a33"}


def test_readable_on_lifts_every_real_team_colour_above_the_floor():
    from cfbtui.ui.theme import MIN_CONTRAST, TERMINAL_BG, contrast, readable_on

    colors = _fixture_colors()
    assert len(colors) > 40
    for c in colors:
        assert contrast(readable_on(c), TERMINAL_BG) >= MIN_CONTRAST, c


def test_readable_on_keeps_good_colours_prefers_alt_then_lightens():
    from cfbtui.ui.theme import luminance, readable_on

    assert readable_on("#f47423") == "#f47423"
    assert readable_on("#001a33", "#ffcc00") == "#ffcc00"  # navy: the gold alt reads
    lifted = readable_on("#001a33", "#000000")  # nothing readable to fall back on
    assert luminance(lifted) > luminance("#001a33")
    assert readable_on("zzz", None).startswith("#")


def test_contrast_ratio_endpoints():
    from cfbtui.ui.theme import contrast

    assert round(contrast("#000000", "#ffffff")) == 21
    assert contrast("#123456", "#123456") == 1


def test_bar_colors_separate_two_similar_reds_and_leave_distinct_pairs_alone():
    from cfbtui.ui.theme import MIN_DISTANCE, bar_colors, distance

    a, h = bar_colors(("#e03030", "#ffffff"), ("#d82828", "#ffcc00"))
    assert distance(a, h) >= MIN_DISTANCE and h == "#ffcc00"
    a, h = bar_colors(("#e03030", None), ("#d82828", None))  # no alts: pushed apart anyway
    assert distance(a, h) >= MIN_DISTANCE
    assert bar_colors(("#e03030", "#fff"), ("#3070e0", "#fff")) == ("#e03030", "#3070e0")
