"""UAT: command line and config file, black box where possible. Nothing here touches the network or the real config dir."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from cfbtui import __version__
from cfbtui.__main__ import resolve
from cfbtui.app import CfbApp
from cfbtui.config import (
    Config,
    FavoritesConfig,
    ViewConfig,
    default_path,
    load_config,
    parse_config,
    save_config,
)
from cfbtui.poll import PollIntervals
from cfbtui.ui.widgets.score_grid import ScoreGrid
from tests.fakes import FakeClient, load_board

ROOT = Path(__file__).resolve().parents[2]
SIZE = (140, 45)


@pytest.fixture
def sandbox_env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    for key in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "HOME", "USERPROFILE"):
        env[key] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_cli(env, *args, timeout=60):
    return subprocess.run(
        [sys.executable, "-m", "cfbtui", *args],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT, timeout=timeout,
    )


def assert_clean_usage_error(proc):
    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "usage:" in proc.stderr


# --- black-box command line ------------------------------------------------------


def test_version(sandbox_env):
    p = run_cli(sandbox_env, "--version")
    assert p.returncode == 0
    assert p.stdout.strip() == f"cfbtui {__version__}"
    assert re.fullmatch(r"cfbtui \d+\.\d+\.\d+", p.stdout.strip())
    assert p.stderr == ""


def test_help_lists_documented_flags(sandbox_env):
    p = run_cli(sandbox_env, "--help")
    assert p.returncode == 0 and "Traceback" not in p.stderr
    for flag in ("--week", "--group", "--glyphs", "--layout", "--config", "--no-config", "--no-update-check", "--version"):
        assert flag in p.stdout, flag
    assert "--selftest" not in p.stdout
    assert "usage:" in p.stdout


def test_help_does_not_create_config_dir(sandbox_env):
    run_cli(sandbox_env, "--help")
    assert list(Path(sandbox_env["LOCALAPPDATA"]).iterdir()) == []


@pytest.mark.parametrize(
    "args",
    [
        ["--glyphs", "bogus"],
        ["--group", "d3"],
        ["--layout", "tiles"],
        ["--week", "0"],
        ["--week", "18"],
        ["--week", "-1"],
        ["--week", "abc"],
        ["--week", "1.5"],
        ["--week", ""],
        ["--week"],
        ["--config"],
        ["--nonsense"],
        ["positional"],
    ],
)
def test_bad_args_are_usage_errors_not_tracebacks(sandbox_env, args):
    assert_clean_usage_error(run_cli(sandbox_env, *args))


def test_bad_glyph_message_names_choices(sandbox_env):
    p = run_cli(sandbox_env, "--glyphs", "bogus")
    for name in ("ascii", "unicode", "emoji", "nerd"):
        assert name in p.stderr


def test_bad_week_message_is_helpful(sandbox_env):
    p = run_cli(sandbox_env, "--week", "99")
    assert "week must be 1 to 17" in p.stderr
    p = run_cli(sandbox_env, "--week", "abc")
    assert "bowls" in p.stderr and "playoff" in p.stderr


def test_flags_accept_case_variants_and_named_weeks():
    for argv, week in (
        (["--week", "bowls"], 16), (["--week", "PLAYOFF"], 17), (["--week", "cfp"], 17),
        (["--week", " 7 "], 7), (["--week", "1"], 1), (["--week", "15"], 15), (["--week", "17"], 17),
    ):
        config, _, _ = resolve([*argv, "--no-config"])
        assert config.view.week == week, argv
    config, _, _ = resolve(["--no-config", "--group", "FCS", "--glyphs", "EMOJI", "--layout", "LIST"])
    assert (config.view.group, config.view.glyph_set, config.view.layout) == ("fcs", "emoji", "list")


def test_week_out_of_range_rejected_in_process():
    for bad in ("0", "18", "-3", "nope"):
        with pytest.raises(SystemExit) as exc:
            resolve(["--no-config", "--week", bad])
        assert exc.value.code == 2


def test_no_update_check_flag():
    config, _, _ = resolve(["--no-config", "--no-update-check"])
    assert config.updates.check is False
    config, _, _ = resolve(["--no-config"])
    assert config.updates.check is True


def test_no_update_check_overrides_file_but_is_not_saved(tmp_path):
    path = tmp_path / "c.toml"
    save_config(Config(), path)
    before = path.read_bytes()
    config, _, _ = resolve(["--config", str(path), "--no-update-check"])
    assert config.updates.check is False
    assert path.read_bytes() == before


def test_config_flag_with_missing_file_does_not_create_it(tmp_path):
    path = tmp_path / "sub" / "c.toml"
    config, loaded, save_path = resolve(["--config", str(path)])
    assert config == Config() and loaded.warnings == () and save_path == path
    assert not path.exists() and not path.parent.exists()


def test_no_config_with_config_path_never_reads_or_touches(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("this is [[ not toml", encoding="utf-8")
    before = path.read_bytes()
    config, loaded, save_path = resolve(["--config", str(path), "--no-config"])
    assert config == Config() and loaded.warnings == () and save_path is None
    assert path.read_bytes() == before


def test_config_pointing_at_directory_warns_not_raises(tmp_path):
    config, loaded, _ = resolve(["--config", str(tmp_path)])
    assert config == Config()
    assert loaded.warnings and "could not read" in loaded.warnings[0]


def test_default_path_is_under_localappdata_cfbtui(sandbox_env, monkeypatch):
    for k, v in sandbox_env.items():
        monkeypatch.setenv(k, v)
    p = default_path()
    assert p.name == "config.toml" and p.parent.name == "cfbtui"
    # platformdirs on Windows resolves the real known-folder, ignoring env overrides, so only check the shape.
    assert str(p).lower().endswith(r"\cfbtui\config.toml") or str(p).endswith("/cfbtui/config.toml")
    assert "cfbtui" not in p.parent.parent.name.lower()  # appauthor=False: no doubled folder


# --- load_config robustness ---------------------------------------------------------


def write(tmp_path, text, name="config.toml", encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
    return p


def test_missing_file_is_defaults_without_warning(tmp_path):
    r = load_config(tmp_path / "nope.toml")
    assert r.config == Config() and r.warnings == ()


def test_empty_file_is_defaults_without_warning(tmp_path):
    r = load_config(write(tmp_path, ""))
    assert r.config == Config() and r.warnings == ()


def test_comments_only_and_whitespace(tmp_path):
    r = load_config(write(tmp_path, "# nothing here\n\n   \n"))
    assert r.config == Config() and r.warnings == ()


@pytest.mark.parametrize(
    "text",
    ["[poll\nlive = 1", "live = = 3", "[view]\nweek = 7\nweek = 8", '"unterminated', "a.b = 1\na = 2"],
)
def test_malformed_toml_gives_defaults_and_one_warning(tmp_path, text):
    r = load_config(write(tmp_path, text))
    assert r.config == Config()
    assert len(r.warnings) == 1 and "not valid TOML" in r.warnings[0]


def test_binary_garbage_and_bad_utf8(tmp_path):
    r = load_config(write(tmp_path, b"\xff\xfe\x00\x01garbage"))
    assert r.config == Config() and r.warnings
    r = load_config(write(tmp_path, b"\x80\x81", name="b.toml"))
    assert r.config == Config() and r.warnings


def test_utf8_bom_file(tmp_path):
    # Notepad on older Windows writes a BOM; README tells users to edit in Notepad.
    r = load_config(write(tmp_path, b"\xef\xbb\xbf[view]\nweek = 4\n"))
    assert r.warnings == (), r.warnings
    assert r.config.view.week == 4


def test_utf16_file_from_notepad_degrades_with_warning(tmp_path):
    r = load_config(write(tmp_path, "[view]\nweek = 4\n", encoding="utf-16"))
    assert r.config == Config() and r.warnings


def test_crlf_line_endings(tmp_path):
    r = load_config(write(tmp_path, '[view]\r\nweek = 4\r\nlayout = "list"\r\n'))
    assert r.warnings == () and r.config.view.week == 4 and r.config.view.layout == "list"


def test_wrong_types_each_warn_and_keep_defaults(tmp_path):
    text = """
[poll]
live = "fast"
idle = true
backoff_max = [1]
away_after = "5m"
[view]
glyph_set = 3
week = "7"
group = 1
layout = false
[favorites]
team_ids = "251"
abbreviations = 5
[updates]
check = "yes"
"""
    r = load_config(write(tmp_path, text))
    assert r.config == Config()
    assert len(r.warnings) == 11, r.warnings


def test_section_not_a_table(tmp_path):
    r = load_config(write(tmp_path, 'poll = 5\nview = "x"\nfavorites = []\nupdates = 1\n'))
    assert r.config == Config() and len(r.warnings) == 4


@pytest.mark.parametrize("value", [0, -1, -0.5, -1e9])
@pytest.mark.parametrize("key", ["live", "idle", "backoff_max", "away_after"])
def test_zero_and_negative_poll_values_are_rejected(tmp_path, key, value):
    r = load_config(write(tmp_path, f"[poll]\n{key} = {value}\n"))
    assert getattr(r.config.poll, key) == getattr(PollIntervals(), key)
    assert len(r.warnings) == 1


def test_live_below_floor_is_clamped_to_five(tmp_path):
    r = load_config(write(tmp_path, "[poll]\nlive = 0.1\n"))
    assert r.config.poll.live == 5.0 and r.warnings
    r = load_config(write(tmp_path, "[poll]\nlive = 5\n"))
    assert r.config.poll.live == 5.0 and r.warnings == ()


def test_other_intervals_floor_at_one(tmp_path):
    r = load_config(write(tmp_path, "[poll]\nidle = 0.001\n"))
    assert r.config.poll.idle == 1.0 and r.warnings


def test_huge_poll_values_clamped(tmp_path):
    r = load_config(write(tmp_path, "[poll]\nlive = 1e12\nidle = 99999999999\n"))
    assert r.config.poll.live == 3600.0 and r.config.poll.idle == 3600.0 and len(r.warnings) == 2


def test_special_floats_do_not_crash(tmp_path):
    r = load_config(write(tmp_path, "[poll]\nlive = inf\nidle = nan\nbackoff_max = -inf\n"))
    p = r.config.poll
    assert p.live <= 3600.0
    # nan must not leak into the scheduler: 'nan > 0' is False so it should be dropped
    assert p.idle == 120.0
    assert p.backoff_max == 120.0


def test_integer_poll_values_accepted(tmp_path):
    r = load_config(write(tmp_path, "[poll]\nlive = 30\nidle = 600\nbackoff_max = 300\naway_after = 60\n"))
    assert r.warnings == ()
    assert r.config.poll == PollIntervals(30.0, 600.0, 300.0, 60.0)


def test_unknown_keys_and_sections_ignored_silently(tmp_path):
    text = '[poll]\nlive = 30\nturbo = true\n[view]\ntheme = "x"\n[future]\nx = 1\n'
    r = load_config(write(tmp_path, text))
    assert r.warnings == () and r.config.poll.live == 30.0


def test_unicode_in_favorites_and_unknown_keys(tmp_path):
    text = (
        '[favorites]\nteam_ids = ["251", "ñandú", "日本"]\nabbreviations = ["tex", "é"]\n'
        '[note]\ntext = "héllo ✓"\n'
    )
    r = load_config(write(tmp_path, text))
    assert r.warnings == ()
    assert r.config.favorites.team_ids == ("251", "ñandú", "日本")
    assert r.config.favorites.abbreviations == ("TEX", "É")


def test_unicode_roundtrip_through_save(tmp_path):
    p = tmp_path / "u.toml"
    cfg = Config(favorites=FavoritesConfig(("日本", "ñ"), ("É",)))
    save_config(cfg, p)
    assert load_config(p).config.favorites == cfg.favorites


def test_favorites_dedup_strip_and_skip_blanks(tmp_path):
    text = '[favorites]\nteam_ids = [" 251 ", "251", "", "  ", 99, true]\nabbreviations = ["tex", "TEX", "Tex"]\n'
    r = load_config(write(tmp_path, text))
    assert r.config.favorites.team_ids == ("251", "99")
    assert r.config.favorites.abbreviations == ("TEX",)
    assert r.warnings  # blanks/bool dropped


def test_enum_values_case_and_whitespace_insensitive(tmp_path):
    r = load_config(write(tmp_path, '[view]\nglyph_set = " ASCII "\ngroup = "FCS"\nlayout = "List"\n'))
    assert r.warnings == ()
    assert (r.config.view.glyph_set, r.config.view.group, r.config.view.layout) == ("ascii", "fcs", "list")


@pytest.mark.parametrize("val", ["0", "18", "-1", "100", "7.5", '"7"', "true"])
def test_bad_week_values(tmp_path, val):
    r = load_config(write(tmp_path, f"[view]\nweek = {val}\n"))
    assert r.config.view.week is None and len(r.warnings) == 1


@pytest.mark.parametrize("week", [1, 15, 16, 17])
def test_good_week_values(tmp_path, week):
    r = load_config(write(tmp_path, f"[view]\nweek = {week}\n"))
    assert r.config.view.week == week and r.warnings == ()


def test_load_never_creates_file_or_dir(tmp_path):
    p = tmp_path / "deep" / "c.toml"
    load_config(p)
    assert not p.exists() and not p.parent.exists()


# --- save / round trip -----------------------------------------------------------------


def test_roundtrip_full_config(tmp_path):
    p = tmp_path / "c.toml"
    cfg = Config(
        poll=PollIntervals(30.5, 200, 90, 45),
        view=ViewConfig("emoji", 9, "fcs", "list"),
        favorites=FavoritesConfig(("251", "2"), ("TEX", "BAMA")),
    )
    save_config(cfg, p)
    r = load_config(p)
    assert r.warnings == () and r.config == cfg


def test_roundtrip_defaults_has_no_week_key(tmp_path):
    p = tmp_path / "c.toml"
    save_config(Config(), p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert "week" not in data["view"]
    assert load_config(p).config == Config()


def test_save_creates_missing_parent_dirs_and_no_tmp_left(tmp_path):
    p = tmp_path / "a" / "b" / "c.toml"
    save_config(Config(), p)
    assert p.exists() and not (p.parent / "c.toml.tmp").exists()


def test_save_overwrites(tmp_path):
    p = tmp_path / "c.toml"
    save_config(Config(favorites=FavoritesConfig(("1",), ())), p)
    save_config(Config(favorites=FavoritesConfig(("2",), ())), p)
    assert load_config(p).config.favorites.team_ids == ("2",)


def test_save_to_unwritable_path_raises_oserror(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(OSError):
        save_config(Config(), blocker / "sub" / "c.toml")  # parent is a file
    d = tmp_path / "dir.toml"
    d.mkdir()
    with pytest.raises(OSError):
        save_config(Config(), d)  # target is a directory


def test_save_rewrites_from_known_keys_only(tmp_path):
    # Unknown keys are tolerated on load; a save rewrites the file from known keys only.
    p = tmp_path / "c.toml"
    p.write_text("[future]\nx = 1\n", encoding="utf-8")
    save_config(load_config(p).config, p)
    assert "future" not in p.read_text(encoding="utf-8")


def test_saved_file_is_valid_toml_with_documented_sections(tmp_path):
    p = tmp_path / "c.toml"
    save_config(Config(), p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert set(data) == {"poll", "view", "favorites", "updates"}
    assert set(data["poll"]) == {"live", "idle", "backoff_max", "away_after"}


# --- README / code agreement ------------------------------------------------------------


def readme_toml():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(r"## Configuration.*?```toml\n(.*?)```", text, re.S).group(1)
    return tomllib.loads(block)


def test_readme_example_parses_without_warnings():
    cfg, warnings = parse_config(readme_toml())
    assert warnings == []
    assert cfg.favorites.team_ids == ("251",) and cfg.favorites.abbreviations == ("TEX",)


def test_readme_documented_defaults_match_code():
    data = readme_toml()
    d = Config()
    assert data["poll"]["live"] == d.poll.live == 20
    assert data["poll"]["idle"] == d.poll.idle == 120
    assert d.poll.backoff_max == 120 and d.poll.away_after == 300
    assert data["view"]["glyph_set"] == d.view.glyph_set == "nerd"
    assert data["view"]["layout"] == d.view.layout == "grid"
    assert data["view"]["group"] == d.view.group == "fbs"
    assert d.view.week is None
    assert data["updates"]["check"] is d.updates.check is True


def test_readme_documents_every_cli_flag():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for flag in ("--week", "--group", "--glyphs", "--layout", "--no-update-check", "--no-config", "--version"):
        assert flag in text, flag


def test_config_docstring_example_matches_defaults():
    import cfbtui.config as c

    body = c.__doc__.split(".. code-block:: toml", 1)[1]
    data = tomllib.loads(re.sub(r"^    ", "", body, flags=re.M))
    d = Config()
    got = data["poll"]
    assert (got["live"], got["idle"], got["backoff_max"], got["away_after"]) == (
        d.poll.live, d.poll.idle, d.poll.backoff_max, d.poll.away_after,
    )
    assert data["view"]["glyph_set"] == d.view.glyph_set


def test_cli_help_shows_default_config_path(sandbox_env):
    p = run_cli(sandbox_env, "--help")
    assert "config.toml" in "".join(p.stdout.split())


# --- app-level: favorites persistence and the "no file until starred" claim ---------------


async def settle(pilot, app, n):
    for _ in range(100):
        await pilot.pause(0.05)
        if len(app.store) >= n:
            return
    raise AssertionError("board did not load")


def fast_app(path, **kw):
    board = load_board("scoreboard_week7_pregame.json")
    kw.setdefault("config", Config())
    app = CfbApp(client=FakeClient(board), intervals=PollIntervals(live=30, idle=30), config_path=path, glyph_set="ascii", **kw)
    return app, board


async def test_no_config_file_until_a_favorite_is_starred(tmp_path):
    path = tmp_path / "cfbtui" / "config.toml"
    app, board = fast_app(path)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        for key in ("g", "v", "t"):
            await pilot.press(key)
            await pilot.pause()
        assert not path.exists() and not path.parent.exists()
        app.query_one(ScoreGrid).card_for(board.games[0].id).focus()
        await pilot.press("1")
        await pilot.pause()
        assert path.exists()
    assert load_config(path).config.favorites.team_ids == (board.games[0].away.id,)


async def test_starring_saves_file_settings_not_flag_overrides(tmp_path):
    path = tmp_path / "config.toml"
    save_config(Config(view=ViewConfig("emoji", 3, "fbs", "grid")), path)
    config, loaded, save_path = resolve(["--config", str(path), "--glyphs", "ascii", "--layout", "list"])
    board = load_board("scoreboard_week7_pregame.json")
    app = CfbApp(
        client=FakeClient(board), intervals=PollIntervals(live=30, idle=30), config=config,
        file_config=loaded.config, config_path=save_path, warnings=loaded.warnings,
    )
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        app.query_one(ScoreGrid).card_for(board.games[0].id).focus()
        await pilot.press("2")
        await pilot.pause()
    saved = load_config(path).config
    assert saved.view == ViewConfig("emoji", 3, "fbs", "grid")
    assert saved.favorites.team_ids == (board.games[0].home.id,)


async def test_no_config_never_writes_even_when_starring(tmp_path):
    config, loaded, save_path = resolve(["--no-config"])
    assert save_path is None
    board = load_board("scoreboard_week7_pregame.json")
    before = set(tmp_path.rglob("*"))
    app = CfbApp(
        client=FakeClient(board), intervals=PollIntervals(live=30, idle=30), config=config,
        file_config=loaded.config, config_path=save_path, glyph_set="ascii",
    )
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        app.query_one(ScoreGrid).card_for(board.games[0].id).focus()
        await pilot.press("1")
        await pilot.pause()
        assert board.games[0].away.id in app.favorites  # still stars for this session
    assert set(tmp_path.rglob("*")) == before


async def test_unwritable_save_path_does_not_crash_app(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    app, board = fast_app(blocker / "sub" / "config.toml")
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        app.query_one(ScoreGrid).card_for(board.games[0].id).focus()
        await pilot.press("1")
        await pilot.pause()
        assert app.is_running
        assert board.games[0].away.id in app.favorites


async def test_readonly_config_file_does_not_crash_app(tmp_path):
    import stat

    path = tmp_path / "config.toml"
    save_config(Config(), path)
    path.chmod(stat.S_IREAD)
    try:
        app, board = fast_app(path)
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app, len(board.games))
            app.query_one(ScoreGrid).card_for(board.games[0].id).focus()
            await pilot.press("1")
            await pilot.pause()
            assert app.is_running
    finally:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)


async def test_unstar_roundtrip_through_file(tmp_path):
    path = tmp_path / "config.toml"
    app, board = fast_app(path)
    gid = board.games[0].id
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        app.query_one(ScoreGrid).card_for(gid).focus()
        await pilot.press("1")
        await pilot.pause()
    saved = load_config(path).config
    app2, _ = fast_app(path, config=saved)
    async with app2.run_test(size=SIZE) as pilot:
        await settle(pilot, app2, len(board.games))
        assert board.games[0].away.id in app2.favorites
        app2.query_one(ScoreGrid).card_for(gid).focus()
        await pilot.press("1")
        await pilot.pause()
    assert load_config(path).config.favorites.team_ids == ()


async def test_corrupt_config_warnings_reach_the_app_and_app_runs(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[poll\nbroken", encoding="utf-8")
    config, loaded, save_path = resolve(["--config", str(path)])
    assert loaded.warnings
    board = load_board("scoreboard_week7_pregame.json")
    app = CfbApp(
        client=FakeClient(board), intervals=PollIntervals(live=30, idle=30), config=config,
        file_config=loaded.config, config_path=save_path, warnings=loaded.warnings, glyph_set="ascii",
    )
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, len(board.games))
        assert app.is_running
