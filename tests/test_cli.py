"""Flags layer over the config file for one run; --no-config ignores the file."""
from __future__ import annotations

import pytest

from cfbtui.__main__ import build_parser, resolve
from cfbtui.config import Config, ViewConfig, save_config


@pytest.fixture
def cfg_file(tmp_path):
    path = tmp_path / "config.toml"
    save_config(Config(view=ViewConfig(glyph_set="emoji", week=3, group="fbs")), path)
    return path


def test_no_flags_means_the_file(cfg_file):
    config, loaded, save_path = resolve(["--config", str(cfg_file)])
    assert config.view == ViewConfig("emoji", 3, "fbs")
    assert save_path == cfg_file and loaded.warnings == ()


def test_flags_override_the_file(cfg_file):
    config, _, _ = resolve(["--config", str(cfg_file), "--week", "6", "--group", "FCS", "--glyphs", "ascii"])
    assert config.view == ViewConfig("ascii", 6, "fcs")


def test_flags_are_not_written_back(cfg_file):
    before = cfg_file.read_text(encoding="utf-8")
    resolve(["--config", str(cfg_file), "--week", "9"])
    assert cfg_file.read_text(encoding="utf-8") == before


def test_no_config_ignores_the_file_and_saves_nowhere(cfg_file):
    config, loaded, save_path = resolve(["--config", str(cfg_file), "--no-config", "--week", "6"])
    assert config.view == ViewConfig("nerd", 6, "fbs")
    assert save_path is None and loaded.warnings == ()


def test_a_corrupt_file_still_resolves_with_a_warning(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[[[", encoding="utf-8")
    config, loaded, _ = resolve(["--config", str(path), "--glyphs", "ascii"])
    assert config.view.glyph_set == "ascii"
    assert loaded.warnings


@pytest.mark.parametrize("bad", [["--week", "0"], ["--week", "16"], ["--week", "x"], ["--group", "d3"], ["--glyphs", "wingdings"]])
def test_bad_flag_values_are_rejected(bad, capsys):
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(bad)
    assert exit_info.value.code == 2
