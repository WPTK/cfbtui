from __future__ import annotations

from cfbtui.config import AlertsConfig, Config, UpdatesConfig, apply_overrides, load_config, parse_config, save_config


def test_default_is_to_check():
    assert Config().updates == UpdatesConfig(check=True)
    config, warnings = parse_config({})
    assert config.updates.check is True and warnings == []


def test_false_is_parsed():
    config, warnings = parse_config({"updates": {"check": False}})
    assert config.updates.check is False and warnings == []


def test_wrong_type_warns_and_keeps_true():
    config, warnings = parse_config({"updates": {"check": "no"}})
    assert config.updates.check is True
    assert "updates.check should be true or false; using true" in warnings


def test_round_trips(tmp_path):
    path = tmp_path / "config.toml"
    save_config(Config(updates=UpdatesConfig(check=False)), path)
    assert load_config(path).config.updates.check is False


def test_override_only_turns_off():
    off = Config(updates=UpdatesConfig(check=False))
    assert apply_overrides(Config(), check_updates=False).updates.check is False
    assert apply_overrides(Config(), check_updates=None).updates.check is True
    assert apply_overrides(off, check_updates=None).updates.check is False


def test_auto_and_alerts_default_on():
    config, warnings = parse_config({})
    assert config.updates.auto is True and config.alerts.enabled is True and warnings == []


def test_auto_and_alerts_are_parsed_and_round_trip(tmp_path):
    config, warnings = parse_config({"updates": {"auto": False}, "alerts": {"enabled": False}})
    assert config.updates == UpdatesConfig(check=True, auto=False) and config.alerts == AlertsConfig(enabled=False)
    assert warnings == []
    path = tmp_path / "config.toml"
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.config == config and loaded.warnings == ()


def test_wrong_types_warn_and_keep_the_defaults():
    config, warnings = parse_config({"updates": {"auto": "yes"}, "alerts": {"enabled": 1}})
    assert config.updates.auto is True and config.alerts.enabled is True
    assert "updates.auto should be true or false; using true" in warnings
    assert "alerts.enabled should be true or false; using true" in warnings
    _, warnings = parse_config({"alerts": "on"})
    assert "[alerts] should be a table; ignored" in warnings
