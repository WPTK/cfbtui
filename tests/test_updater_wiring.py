"""The updater wired into the app and the entry point, with a fake updater: no network, no real files."""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
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
SUMS = "SHA256SUMS"
LINK = "https://example.test/releases/latest"
_major, _minor, _patch = (int(p) for p in __version__.split(".")[:3])
PATCH = f"{_major}.{_minor}.{_patch + 1}"
MAJOR = f"{_major + 1}.0.0"


def info(version: str = PATCH, *, names: tuple[str, ...] = (NAME, "SHA256SUMS")) -> UpdateInfo:
    return UpdateInfo(version, LINK, tuple(Asset(n, f"https://example.test/{n}", 10) for n in names))


class FakeUpdater:
    def __init__(self, kind: str = "binary", asset_name: str | None = NAME, fail: Exception | None = None) -> None:
        self.kind, self.asset_name, self.fail = kind, asset_name, fail
        self.target = Path("bin/cfbtui")
        self.staged = SimpleNamespace(name="staged")
        self.stage_calls: list[UpdateInfo] = []
        self.closed = 0

    def stage(self, found: UpdateInfo):
        self.stage_calls.append(found)
        if self.fail is not None:
            raise self.fail
        return self.staged

    def close(self, keep=None) -> None:
        self.closed += 1
        self.kept = keep


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
        ("binary", True, False, PATCH, (NAME, SUMS), "download"),
        ("binary", True, False, f"{_major}.{_minor + 1}.0", (NAME, SUMS), "download"),
        ("binary", True, False, PATCH, (NAME,), "link"),  # no SHA256SUMS
        ("binary", False, False, PATCH, (NAME, SUMS), "link"),
        ("binary", True, True, PATCH, (NAME, SUMS), "link"),
        ("binary", True, False, MAJOR, (NAME, SUMS), "link"),
        ("binary", True, False, PATCH, ("cfbtui-other", SUMS), "link"),
        ("binary", True, False, "not-a-version", (NAME, SUMS), "link"),
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


class StubStaged:
    def __init__(self) -> None:
        self.discarded = 0

    def discard(self) -> None:
        self.discarded += 1


class StubApp:
    staged = None
    restart_requested = False
    return_code = 0
    config = Config()

    def __init__(self, **kwargs) -> None:
        StubApp.kwargs = kwargs

    def run(self) -> None:
        self.staged = StubApp.staged_after_run
        self.restart_requested = StubApp.restart_after_run
        self.return_code = StubApp.code_after_run
        self.config = StubApp.config_after_run


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
    calls = SimpleNamespace(cleanup=[], sweep=[], restart=[])
    monkeypatch.setattr("cfbtui.app.CfbApp", StubApp)
    monkeypatch.setattr("cfbtui.selfupdate.cleanup_old", calls.cleanup.append)
    monkeypatch.setattr("cfbtui.selfupdate.sweep", calls.sweep.append)
    monkeypatch.setattr(entry, "restart", lambda target, args: calls.restart.append((target, args)))
    monkeypatch.setattr(sys, "argv", ["cfbtui", "--no-config"])

    def setup(updater, staged=None, restart=False, code=0, auto=True):
        monkeypatch.setattr("cfbtui.selfupdate.Updater.detect", lambda version: updater)
        StubApp.staged_after_run, StubApp.restart_after_run, StubApp.code_after_run = staged, restart, code
        StubApp.config_after_run = Config(updates=UpdatesConfig(auto=auto))

    calls.setup = setup
    return calls


def test_main_applies_a_staged_update_once_after_the_app_exits(main_env):
    updater = MainUpdater()
    main_env.setup(updater, staged="S")
    assert entry.main(["--no-config"]) == 0
    assert updater.applied == ["S"] and main_env.restart == [] and main_env.cleanup == [Path("bin/cfbtui")]
    assert StubApp.kwargs["updater"] is updater


def test_main_restarts_only_when_asked_and_only_after_a_good_apply(main_env):
    updater = MainUpdater()
    main_env.setup(updater, staged="S", restart=True)
    entry.main(["--no-config"])
    assert main_env.restart == [(Path("bin/cfbtui"), ["--no-config"])]


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


def test_main_discards_the_update_when_auto_was_turned_off_after_staging(main_env):
    updater, staged = MainUpdater(), StubStaged()
    main_env.setup(updater, staged=staged, auto=False)
    entry.main(["--no-config"])
    assert updater.applied == [] and staged.discarded == 1


def test_restart_now_installs_even_with_auto_off(main_env):
    updater, staged = MainUpdater(), StubStaged()
    main_env.setup(updater, staged=staged, auto=False, restart=True)
    entry.main(["--no-config"])
    assert updater.applied == [staged] and len(main_env.restart) == 1


def test_main_discards_the_update_after_an_abnormal_exit(main_env):
    updater, staged = MainUpdater(), StubStaged()
    main_env.setup(updater, staged=staged, code=1, restart=True)
    entry.main(["--no-config"])
    assert updater.applied == [] and staged.discarded == 1 and main_env.restart == []


def test_main_cleans_up_only_for_binaries_and_survives_any_error(main_env, monkeypatch):
    main_env.setup(MainUpdater("pip"))
    entry.main(["--no-config"])
    assert main_env.cleanup == [] and main_env.sweep == []

    def explode(target):
        raise RuntimeError("anything")

    monkeypatch.setattr("cfbtui.selfupdate.cleanup_old", explode)
    main_env.setup(MainUpdater("binary"))
    assert entry.main(["--no-config"]) == 0


def test_main_sweeps_the_stage_folder_for_binaries(main_env):
    main_env.setup(MainUpdater("binary"))
    entry.main(["--no-config"])
    assert main_env.sweep == [Path("bin")]


def test_no_update_check_hands_the_app_no_updater(main_env):
    main_env.setup(MainUpdater())
    entry.main(["--no-config", "--no-update-check"])
    assert StubApp.kwargs["updater"] is None and StubApp.kwargs["update_check"] is None


def test_updater_stage_needs_the_asset_and_the_sums_file(tmp_path):
    updater = Updater("binary", NAME, tmp_path / NAME, __version__)
    for names in ((NAME,), ("SHA256SUMS",)):
        with pytest.raises(UpdateError, match="has no"):
            updater.stage(info(names=names))


# --- restart: a clean PyInstaller environment ------------------------------------------


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_restart_drops_the_pyinstaller_environment_and_keeps_the_flags(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "/old")
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("KEEP_ME", "1")
    seen = []
    execve = lambda path, argv, env: seen.append(("execve", str(path), argv, env))  # noqa: E731
    call = lambda argv, env: seen.append(("call", argv[0], argv, env)) or 0  # noqa: E731
    if platform == "win32":
        with pytest.raises(SystemExit):
            entry.restart(Path("/bin/cfbtui"), ["--no-config", "--week", "3"], execve, call)
    else:
        entry.restart(Path("/bin/cfbtui"), ["--no-config", "--week", "3"], execve, call)
    (kind, _, argv, env), = seen
    assert kind == ("call" if platform == "win32" else "execve")
    assert argv[1:] == ["--no-config", "--week", "3"]
    assert not any(k.startswith("_PYI_") for k in env)
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and env["KEEP_ME"] == "1"


# --- cancelling, sweeping and the sums download ----------------------------------------


class SlowUpdater(FakeUpdater):
    """stage() waits until close() is called, then fails the way the real one does."""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.cancel = threading.Event()

    def stage(self, found):
        self.started.set()
        assert self.cancel.wait(5), "close() never reached the running stage"
        raise UpdateError("the update was cancelled")

    def close(self, keep=None) -> None:
        super().close(keep)
        self.cancel.set()


async def test_quitting_while_the_update_is_downloading_stops_it():
    updater = SlowUpdater()
    app = make_app(info(), updater)
    started = time.monotonic()
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, updater.started.is_set)
    assert updater.closed == 1 and updater.kept is None and app.staged is None
    assert time.monotonic() - started < 4


def real_updater(tmp_path, handler) -> Updater:
    return Updater("binary", NAME, tmp_path / NAME, __version__, httpx.Client(transport=httpx.MockTransport(handler)))


def sums_asset(url="https://example.test/SHA256SUMS", size=10) -> Asset:
    return Asset("SHA256SUMS", url, size)


def test_sums_text_reads_a_good_file(tmp_path):
    updater = real_updater(tmp_path, lambda r: httpx.Response(200, content=b"abc"))
    assert updater._sums_text(sums_asset()) == "abc"


@pytest.mark.parametrize(
    ("handler", "asset", "message"),
    [
        (lambda r: httpx.Response(200 if r.url.host == "evil.test" else 302, headers={"location": "http://evil.test/x"}),
         sums_asset(), "refusing"),
        (lambda r: httpx.Response(200, content=b"x" * (2 << 20)), sums_asset(size=2 << 20), "too large"),
        (lambda r: httpx.Response(200, content=b"x" * (2 << 20)), sums_asset(), "larger than"),
        (lambda r: httpx.Response(404), sums_asset(), "HTTP 404"),
        (lambda r: httpx.Response(200, content=b"\xff\xfe"), sums_asset(), "could not read"),
        (lambda r: httpx.Response(200), sums_asset("http://example.test/SHA256SUMS"), "refusing"),
    ],
    ids=["redirect-to-http", "oversize-listed", "oversize-sent", "non-200", "not-utf8", "http-url"],
)
def test_sums_text_refuses_bad_downloads(tmp_path, handler, asset, message):
    with pytest.raises(UpdateError, match=message):
        real_updater(tmp_path, handler)._sums_text(asset)


def test_sums_text_after_close_is_an_update_error_not_a_crash(tmp_path):
    updater = real_updater(tmp_path, lambda r: httpx.Response(200, content=b"abc"))
    updater.close()
    with pytest.raises(UpdateError):
        updater._sums_text(sums_asset())


def test_stage_after_close_does_nothing(tmp_path):
    updater = real_updater(tmp_path, lambda r: httpx.Response(200, content=b"abc"))
    updater.close()
    with pytest.raises(UpdateError, match="cancelled"):
        updater.stage(info())
    assert not (tmp_path / ".cfbtui-update").exists()


class StageUpdater(MainUpdater):
    def __init__(self, fail: Exception | None = None) -> None:
        super().__init__("binary")
        self.stage_error = fail

    def stage(self, release):
        if self.stage_error is not None:
            raise self.stage_error
        return "S"


@pytest.fixture
def headless(main_env, monkeypatch):
    found = {"info": info()}

    async def check(current):
        return found["info"]

    monkeypatch.setattr("cfbtui.update.check_for_update", check)
    monkeypatch.setattr("cfbtui.update.asset_name", lambda *a: NAME)
    main_env.found = found
    return main_env


def test_update_test_installs_without_the_app(headless, capsys):
    updater = StageUpdater()
    headless.setup(updater)
    assert entry.main(["--no-config", "--update-test", "apply"]) == 0
    assert updater.applied == ["S"] and headless.restart == []
    assert f"cfbtui {PATCH} installed" in capsys.readouterr().out


def test_update_test_restart_starts_the_new_binary_after_a_good_apply(headless):
    headless.setup(StageUpdater())
    assert entry.main(["--no-config", "--update-test", "restart"]) == 0
    assert headless.restart == [(Path("bin/cfbtui"), ["--no-config", "--update-test", "restart"])]


def test_update_test_failures_exit_nonzero_and_install_nothing(headless, capsys):
    updater = StageUpdater(fail=UpdateError("download does not match SHA256SUMS"))
    headless.setup(updater)
    assert entry.main(["--no-config", "--update-test", "restart"]) == 1
    assert updater.applied == [] and headless.restart == []
    assert "does not match SHA256SUMS" in capsys.readouterr().err


def test_update_test_with_nothing_newer_says_so(headless, capsys):
    headless.found["info"] = None
    headless.setup(StageUpdater())
    assert entry.main(["--no-config", "--update-test", "apply"]) == 0
    assert f"cfbtui {__version__}: up to date" in capsys.readouterr().out


def test_update_test_refuses_a_release_that_would_not_download(headless):
    headless.found["info"] = info(MAJOR)
    headless.setup(StageUpdater())
    assert entry.main(["--no-config", "--update-test", "apply"]) == 2


def test_update_test_needs_a_binary(main_env):
    main_env.setup(MainUpdater("pip"))
    assert entry.main(["--no-config", "--update-test", "apply"]) == 2
