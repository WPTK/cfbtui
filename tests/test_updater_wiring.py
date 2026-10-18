"""The updater wired into the app and the entry point, with a fake updater: no network, no real files."""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from cfbtui import __main__ as entry
from cfbtui import __version__
from cfbtui.app import CfbApp
from cfbtui.config import Config, UpdatesConfig
from cfbtui.selfupdate import RollbackError, UpdateError, Updater
from cfbtui.ui.glyphs import ASCII
from cfbtui.ui.screens.settings import SettingsScreen
from cfbtui.ui.widgets.status_bar import StatusBar, StatusView, format_status
from cfbtui.update import Asset, UpdateInfo, decide
from tests.fakes import FakeClient, load_board
from tests.test_app_smoke import FAST, SIZE, wait_for

NAME = "cfbtui-linux-x86_64"
LINK = "https://example.test/releases/latest"
_major, _minor, _patch = (int(p) for p in __version__.split(".")[:3])
PATCH = f"{_major}.{_minor}.{_patch + 1}"
MAJOR = f"{_major + 1}.0.0"


def info(version: str = PATCH, *, names: tuple[str, ...] = (NAME, "SHA256SUMS")) -> UpdateInfo:
    return UpdateInfo(version, LINK, tuple(Asset(n, f"https://example.test/{n}", 10) for n in names))


class FakeUpdater:
    def __init__(self, kind: str = "binary", asset_name: str | None = NAME, fail: Exception | None = None) -> None:
        self.kind, self.asset_name, self.fail = kind, asset_name, fail
        self.target = "target"
        self.staged = SimpleNamespace(name="staged")
        self.stage_calls: list[UpdateInfo] = []
        self.closed = 0

    def stage(self, found: UpdateInfo):
        self.stage_calls.append(found)
        if self.fail is not None:
            raise self.fail
        return self.staged

    def close(self) -> None:
        self.closed += 1


def make_app(found: UpdateInfo | None, updater: FakeUpdater | None, *, auto: bool = True, config_path="x") -> CfbApp:
    async def check():
        return found

    config = Config(updates=UpdatesConfig(check=True, auto=auto))
    return CfbApp(client=FakeClient(load_board("pairs/final_after.json")), intervals=FAST, glyph_set="ascii",
                  config=config, config_path=config_path, update_check=check, updater=updater)


def messages(app: CfbApp) -> list[str]:
    return [n.message for n in app._notifications]


async def settle(pilot, app: CfbApp, text: str) -> None:
    await wait_for(pilot, lambda: any(text in m for m in messages(app)))


# --- the decision ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "auto", "no_config", "version", "names", "expected"),
    [
        ("binary", True, False, PATCH, (NAME,), "download"),
        ("binary", True, False, f"{_major}.{_minor + 1}.0", (NAME,), "download"),
        ("binary", False, False, PATCH, (NAME,), "link"),
        ("binary", True, True, PATCH, (NAME,), "link"),
        ("binary", True, False, MAJOR, (NAME,), "link"),
        ("binary", True, False, PATCH, ("cfbtui-other",), "link"),
        ("binary", True, False, "not-a-version", (NAME,), "link"),
        ("pip", True, False, PATCH, (NAME,), "message"),
        ("pipx", False, True, MAJOR, (), "message"),
        ("uv", True, False, PATCH, (), "message"),
    ],
)
def test_decide(kind, auto, no_config, version, names, expected):
    found = info(version, names=names)
    assert decide(kind, auto=auto, no_config=no_config, current=__version__, info=found, asset=NAME) == expected


def test_decide_without_a_platform_asset_name_is_the_link():
    assert decide("binary", auto=True, no_config=False, current=__version__, info=info(), asset=None) == "link"


# --- the app ---------------------------------------------------------------------


async def test_a_binary_stages_toasts_and_shows_the_marker():
    updater = FakeUpdater()
    app = make_app(info(), updater)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, "takes over when you quit")
        assert f"cfbtui {PATCH} downloaded" in " ".join(messages(app))
        assert app.staged is updater.staged
        await pilot.pause(1.2)  # the status line repaints once a second
        assert f"update {PATCH} ready" in app.query_one(StatusBar).text
    assert updater.stage_calls == [info()] and updater.closed == 1


@pytest.mark.parametrize("kind", ["pip", "pipx", "uv"])
async def test_pip_kinds_get_the_upgrade_message(kind):
    updater = FakeUpdater(kind)
    app = make_app(info(), updater)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, "Upgrade with:")
        assert {"pip": "pip install -U", "pipx": "pipx upgrade", "uv": "uv tool upgrade"}[kind] in " ".join(messages(app))
    assert updater.stage_calls == [] and app.staged is None


@pytest.mark.parametrize(
    "case",
    ["auto_off", "no_asset", "major", "no_config", "no_updater"],
)
async def test_everything_else_shows_the_link_and_downloads_nothing(case):
    updater = FakeUpdater(asset_name=None if case == "no_asset" else NAME)
    kwargs = {"auto": case != "auto_off", "config_path": None if case == "no_config" else "x"}
    app = make_app(info(MAJOR if case == "major" else PATCH), None if case == "no_updater" else updater, **kwargs)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, LINK)
    assert updater.stage_calls == [] and app.staged is None


@pytest.mark.parametrize("failure", [UpdateError("download does not match SHA256SUMS"), RuntimeError("boom")])
async def test_a_failed_download_warns_once_and_leaves_nothing_staged(failure):
    updater = FakeUpdater(fail=failure)
    app = make_app(info(), updater)
    async with app.run_test(size=SIZE) as pilot:
        await settle(pilot, app, "Could not download")
        await pilot.pause(0.3)
        warnings = [n for n in app._notifications if n.severity == "warning"]
        assert len(warnings) == 1 and LINK in warnings[0].message
        assert app.staged is None and "ready" not in app.query_one(StatusBar).text


async def test_no_update_check_means_no_check_and_no_download():
    updater = FakeUpdater()
    app = CfbApp(client=FakeClient(load_board("pairs/final_after.json")), intervals=FAST, glyph_set="ascii",
                 updater=updater)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.3)
    assert updater.stage_calls == [] and app.staged is None


async def test_the_settings_screen_offers_restart_only_when_staged_and_quits_when_chosen():
    gate = asyncio.Event()

    async def check():
        await gate.wait()
        return info()

    app = make_app(None, FakeUpdater())
    app.update_check = check
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("S")
        assert isinstance(app.screen, SettingsScreen) and app.screen.on_restart is None
        await pilot.press("escape")
        gate.set()
        await settle(pilot, app, "takes over when you quit")
        await pilot.press("S")
        assert app.screen.on_restart is not None
        await pilot.press("up")  # wraps to the last row, Restart now
        assert not app.restart_requested
        await pilot.press("enter")
        await pilot.pause()
        assert app.restart_requested


def test_the_status_marker_is_ascii_and_dropped_before_health():
    view = StatusView(update_ready="9.9.9")
    assert "update 9.9.9 ready" in format_status(view, ASCII)
    assert format_status(view, ASCII, width=14) == format_status(StatusView(), ASCII, width=14)


# --- the entry point -------------------------------------------------------------


class StubApp:
    staged = None
    restart_requested = False

    def __init__(self, **kwargs) -> None:
        StubApp.kwargs = kwargs

    def run(self) -> None:
        self.staged = StubApp.staged_after_run
        self.restart_requested = StubApp.restart_after_run


class MainUpdater(FakeUpdater):
    def __init__(self, kind="binary", fail: Exception | None = None) -> None:
        super().__init__(kind)
        self.apply_error = fail
        self.applied: list[object] = []

    def apply(self, staged) -> None:
        self.applied.append(staged)
        if self.apply_error is not None:
            raise self.apply_error


@pytest.fixture
def main_env(monkeypatch):
    calls = SimpleNamespace(cleanup=[], restart=[])
    monkeypatch.setattr("cfbtui.app.CfbApp", StubApp)
    monkeypatch.setattr("cfbtui.selfupdate.cleanup_old", calls.cleanup.append)
    monkeypatch.setattr(entry, "restart", lambda target, args: calls.restart.append((target, args)))
    monkeypatch.setattr(sys, "argv", ["cfbtui", "--no-config"])

    def setup(updater, staged=None, restart=False):
        monkeypatch.setattr("cfbtui.selfupdate.Updater.detect", lambda version: updater)
        StubApp.staged_after_run, StubApp.restart_after_run = staged, restart

    calls.setup = setup
    return calls


def test_main_applies_a_staged_update_once_after_the_app_exits(main_env):
    updater = MainUpdater()
    main_env.setup(updater, staged="S")
    assert entry.main(["--no-config"]) == 0
    assert updater.applied == ["S"] and main_env.restart == [] and main_env.cleanup == ["target"]
    assert StubApp.kwargs["updater"] is updater


def test_main_restarts_only_when_asked_and_only_after_a_good_apply(main_env):
    updater = MainUpdater()
    main_env.setup(updater, staged="S", restart=True)
    entry.main(["--no-config"])
    assert main_env.restart == [("target", ["--no-config"])]


def test_main_prints_recovery_instructions_and_does_not_restart_on_rollback_error(main_env, capsys):
    updater = MainUpdater(fail=RollbackError("rename X.old to X to recover"))
    main_env.setup(updater, staged="S", restart=True)
    assert entry.main(["--no-config"]) == 0
    assert "rename X.old to X to recover" in capsys.readouterr().err and main_env.restart == []


def test_main_survives_a_failed_apply(main_env, capsys):
    main_env.setup(MainUpdater(fail=UpdateError("disk full")), staged="S")
    assert entry.main(["--no-config"]) == 0
    assert "disk full" in capsys.readouterr().err


def test_main_applies_nothing_when_nothing_was_staged(main_env):
    updater = MainUpdater()
    main_env.setup(updater)
    entry.main(["--no-config"])
    assert updater.applied == []


def test_main_cleans_up_only_for_binaries_and_survives_any_error(main_env, monkeypatch):
    main_env.setup(MainUpdater("pip"))
    entry.main(["--no-config"])
    assert main_env.cleanup == []

    def explode(target):
        raise RuntimeError("anything")

    monkeypatch.setattr("cfbtui.selfupdate.cleanup_old", explode)
    main_env.setup(MainUpdater("binary"))
    assert entry.main(["--no-config"]) == 0


def test_no_update_check_hands_the_app_no_updater(main_env):
    main_env.setup(MainUpdater())
    entry.main(["--no-config", "--no-update-check"])
    assert StubApp.kwargs["updater"] is None and StubApp.kwargs["update_check"] is None


def test_updater_stage_needs_the_asset_and_the_sums_file(tmp_path):
    updater = Updater("binary", NAME, tmp_path / NAME, __version__)
    for names in ((NAME,), ("SHA256SUMS",)):
        with pytest.raises(UpdateError, match="has no"):
            updater.stage(info(names=names))
