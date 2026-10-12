"""Config loading is tolerant, saving round-trips, and flags beat the file."""
from __future__ import annotations

from dataclasses import replace

from cfbtui.config import (
    Config,
    FavoritesConfig,
    ViewConfig,
    apply_overrides,
    default_path,
    favorite_ids,
    load_config,
    save_config,
)
from cfbtui.poll import PollIntervals


def write(tmp_path, text: str):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_is_the_defaults_and_is_not_created(tmp_path):
    path = tmp_path / "nested" / "config.toml"
    result = load_config(path)
    assert result.config == Config()
    assert result.warnings == ()
    assert not path.exists() and not path.parent.exists()


def test_empty_file_is_the_defaults(tmp_path):
    result = load_config(write(tmp_path, ""))
    assert result.config == Config() and result.warnings == ()


def test_default_path_is_under_a_cfbtui_directory():
    assert default_path().parent.name == "cfbtui" and default_path().name == "config.toml"


def test_a_full_file_loads(tmp_path):
    result = load_config(
        write(
            tmp_path,
            '[poll]\nlive = 10\nidle = 120.5\nbackoff_max = 60\n'
            '[view]\nglyph_set = "ASCII"\nweek = 6\ngroup = "FCS"\n'
            '[favorites]\nteam_ids = ["251", "201"]\nabbreviations = ["tex"]\n',
        )
    )
    cfg = result.config
    assert result.warnings == ()
    assert cfg.poll == PollIntervals(live=10.0, idle=120.5, backoff_max=60.0)
    assert cfg.view == ViewConfig(glyph_set="ascii", week=6, group="fcs")
    assert cfg.favorites == FavoritesConfig(("251", "201"), ("TEX",))


def test_unknown_keys_and_sections_are_ignored_quietly(tmp_path):
    result = load_config(write(tmp_path, 'future = 1\n[poll]\nlive = 15\nturbo = true\n[sound]\nvolume = 11\n'))
    assert result.config.poll.live == 15.0
    assert result.warnings == ()


def test_wrong_typed_values_fall_back_with_a_warning_each(tmp_path):
    result = load_config(
        write(
            tmp_path,
            '[poll]\nlive = "fast"\nidle = -5\nbackoff_max = true\n'
            '[view]\nglyph_set = "wingdings"\nweek = 99\ngroup = 3\n'
            '[favorites]\nteam_ids = "251"\n',
        )
    )
    assert result.config == Config()
    text = "\n".join(result.warnings)
    for name in ("poll.live", "poll.idle", "poll.backoff_max", "view.glyph_set", "view.week", "view.group", "favorites.team_ids"):
        assert name in text, name


def test_a_good_value_survives_a_bad_neighbour(tmp_path):
    result = load_config(write(tmp_path, '[poll]\nlive = "x"\nidle = 90\n'))
    assert result.config.poll.idle == 90.0 and result.config.poll.live == PollIntervals().live
    assert len(result.warnings) == 1


def test_a_section_of_the_wrong_shape_is_ignored(tmp_path):
    result = load_config(write(tmp_path, 'poll = 3\n'))
    assert result.config == Config()
    assert "[poll]" in result.warnings[0]


def test_corrupt_toml_is_the_defaults_plus_a_warning(tmp_path):
    result = load_config(write(tmp_path, "[poll\nlive = = 3"))
    assert result.config == Config()
    assert len(result.warnings) == 1 and "not valid TOML" in result.warnings[0]


def test_binary_garbage_is_the_defaults_plus_a_warning(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes(b"\xff\xfe\x00\x01")
    result = load_config(path)
    assert result.config == Config() and result.warnings


def test_a_directory_where_the_file_should_be_does_not_crash(tmp_path):
    result = load_config(tmp_path)
    assert result.config == Config()


def test_non_string_favorites_entries_are_skipped_with_a_warning(tmp_path):
    result = load_config(write(tmp_path, '[favorites]\nteam_ids = ["251", 7.5, ""]\n'))
    assert result.config.favorites.team_ids == ("251",)
    assert result.warnings


def test_round_trip_through_save(tmp_path):
    original = Config(
        poll=PollIntervals(live=12, idle=240, backoff_max=90),
        view=ViewConfig(glyph_set="emoji", week=9, group="fcs"),
        favorites=FavoritesConfig(("251",), ("OU",)),
    )
    path = tmp_path / "deep" / "cfbtui" / "config.toml"
    assert save_config(original, path) == path
    result = load_config(path)
    assert result.config == original and result.warnings == ()
    assert not path.with_name("config.toml.tmp").exists()


def test_round_trip_keeps_the_current_week_unset(tmp_path):
    path = tmp_path / "config.toml"
    save_config(Config(), path)
    assert "week" not in path.read_text(encoding="utf-8")
    assert load_config(path).config == Config()


def test_flags_override_the_file_only_where_given():
    base = Config(view=ViewConfig(glyph_set="emoji", week=3, group="fbs"))
    assert apply_overrides(base) == base
    out = apply_overrides(base, week=6, group="fcs", glyph_set="ascii")
    assert out.view == ViewConfig("ascii", 6, "fcs")
    assert apply_overrides(base, glyph_set="ascii").view == replace(base.view, glyph_set="ascii")
    assert base.view.glyph_set == "emoji", "the original is untouched"


def test_favorite_ids_resolve_abbreviations_against_teams_seen():
    cfg = Config(favorites=FavoritesConfig(("1",), ("TEX",)))
    assert favorite_ids(cfg) == {"1"}
    assert favorite_ids(cfg, [("251", "TEX"), ("201", "OU")]) == {"1", "251"}
