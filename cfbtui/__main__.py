"""Command-line entry point: ``python -m cfbtui`` or the ``cfbtui`` console script.

Flags override the config file for this run only and are never written back.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
from functools import partial
from pathlib import Path

from cfbtui import __version__
from cfbtui.config import GROUPS, LAYOUTS, Config, LoadResult, apply_overrides, default_path, load_config
from cfbtui.espn.periods import LAST_REGULAR_WEEK, MAX_WEEK, MIN_WEEK, NAMED
from cfbtui.ui.glyphs import GLYPH_SET_NAMES


def _week(text: str) -> int:
    if text.strip().lower() in NAMED:
        return NAMED[text.strip().lower()]
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a week number, 'bowls' or 'playoff'") from None
    if not MIN_WEEK <= value <= MAX_WEEK:
        raise argparse.ArgumentTypeError(f"week must be {MIN_WEEK} to {MAX_WEEK} (16 = bowls, 17 = playoff)")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cfbtui",
        description="A colorful college football scoreboard for the terminal.",
    )
    parser.add_argument("--version", action="version", version=f"cfbtui {__version__}")
    parser.add_argument(
        "--week",
        type=_week,
        metavar="N",
        help=f"start on week N ({MIN_WEEK}-{LAST_REGULAR_WEEK}), 'bowls' or 'playoff' instead of the current week",
    )
    parser.add_argument("--group", type=str.lower, choices=sorted(GROUPS), help="FBS or FCS board")
    parser.add_argument(
        "--glyphs",
        type=str.lower,
        choices=GLYPH_SET_NAMES,
        metavar="NAME",
        help=f"glyph set: {', '.join(GLYPH_SET_NAMES)}",
    )
    parser.add_argument("--layout", type=str.lower, choices=LAYOUTS, help="card grid or one line per game")
    parser.add_argument("--config", type=Path, metavar="PATH", help=f"config file (default: {default_path()})")
    parser.add_argument("--no-config", action="store_true", help="ignore the config file and do not save to it")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--update-test", choices=("apply", "restart"), help=argparse.SUPPRESS)
    parser.add_argument("--no-update-check", action="store_true", help="do not look for a newer release")
    return parser


def resolve(argv: list[str] | None = None) -> tuple[Config, LoadResult, Path | None]:
    """Parse flags, load the file, and layer the flags on top.

    Returns the effective config, the raw load result (for its warnings) and
    the path favorites will be saved to (``None`` under ``--no-config``).
    """
    args = build_parser().parse_args(argv)
    if args.no_config:
        loaded = LoadResult(Config())
        save_path = None
    else:
        save_path = args.config if args.config is not None else default_path()
        loaded = load_config(save_path)
    config = apply_overrides(
        loaded.config,
        week=args.week,
        group=args.group,
        glyph_set=args.glyphs,
        layout=args.layout,
        check_updates=False if args.no_update_check else None,
    )
    return config, loaded, save_path


def selftest() -> int:
    """Start the app headless against an empty board, so a frozen build proves its imports, CSS and tzdata."""
    import asyncio
    from zoneinfo import ZoneInfo

    from cfbtui.app import CfbApp
    from cfbtui.espn.models import Scoreboard, Summary

    class EmptyBoard:
        async def scoreboard(self, *, week: int | None = None, group: int = 80) -> Scoreboard:
            return Scoreboard()

        async def rankings(self) -> tuple:
            return ()

        async def summary(self, event_id: str) -> Summary:
            raise NotImplementedError  # the selftest never opens a game

    async def run() -> None:
        app = CfbApp(client=EmptyBoard(), config=Config())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()

    ZoneInfo("America/New_York")
    asyncio.run(run())
    print("selftest ok")
    return 0


def restart(target: Path, args: list[str], execve=os.execve, call=subprocess.call) -> None:
    """Start the installed binary again with the same arguments and a clean PyInstaller environment.

    Windows has no exec, so it waits for the child.
    """
    from cfbtui.selfupdate import child_env

    if sys.platform == "win32":
        raise SystemExit(call([str(target), *args], env=child_env()))
    execve(target, [str(target), *args], child_env())


def install_update(updater, staged, app) -> bool:
    """Swap the staged binary in after the app has exited, or discard it. Returns whether it was installed.

    A staged update is installed only if cfbtui exited normally and auto-update is still on (or the user chose
    Restart now). A failure leaves the old version in place and says why on stderr.
    """
    from cfbtui.selfupdate import UpdateError

    if app.return_code not in (0, None) or not (app.config.updates.auto or app.restart_requested):
        staged.discard()
        return False
    try:
        updater.apply(staged)
    except UpdateError as exc:  # RollbackError says how to recover by hand
        print(f"cfbtui: the update was not installed: {exc}", file=sys.stderr)
        return False
    return True


def update_test(mode: str, updater, argv: list[str]) -> int:
    """Run the update path with no TUI (the end-to-end workflow cannot drive one): check, stage and probe
    a newer release, install it, and for "restart" start the new binary. Exit 1 when the update fails."""
    import asyncio
    from types import SimpleNamespace

    from cfbtui.selfupdate import UpdateError
    from cfbtui.update import asset_name, check_for_update, decide

    info = asyncio.run(check_for_update(__version__))
    if info is None:
        print(f"cfbtui {__version__}: up to date")
        return 0
    if decide(updater.kind, auto=True, no_config=False, current=__version__, info=info,
              asset=asset_name()) != "download":
        print("cfbtui: this release would not be downloaded", file=sys.stderr)
        return 2
    try:
        staged = updater.stage(info)
    except UpdateError as exc:
        print(f"cfbtui: could not download {info.version}: {exc}", file=sys.stderr)
        return 1
    app = SimpleNamespace(return_code=0, config=Config(), restart_requested=mode == "restart")
    if not install_update(updater, staged, app):
        return 1
    print(f"cfbtui {info.version} installed")
    if mode == "restart":
        restart(updater.target, argv)
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None and "--selftest" in sys.argv[1:]:
        return selftest()
    config, loaded, save_path = resolve(argv)

    # Imported lazily so `--version` stays instant and never touches the terminal.
    from cfbtui.app import CfbApp
    from cfbtui.selfupdate import Updater, cleanup_old, sweep
    from cfbtui.update import check_for_update

    update_check = partial(check_for_update, __version__) if config.updates.check else None
    updater = Updater.detect(__version__)
    if updater.kind == "binary":
        with contextlib.suppress(Exception):
            cleanup_old(updater.target)  # drop the previous version, or restore it after a crashed swap
            sweep(updater.target.parent)  # and any download an earlier run left behind
    mode = build_parser().parse_args(argv).update_test
    if mode is not None:
        if updater.kind != "binary":
            print("cfbtui: --update-test needs a standalone binary", file=sys.stderr)
            return 2
        return update_test(mode, updater, sys.argv[1:] if argv is None else argv)
    app_updater = None if update_check is None else updater  # --no-update-check: no checking and no downloading
    app = CfbApp(
        config=config,
        file_config=loaded.config,
        config_path=save_path,
        warnings=loaded.warnings,
        update_check=update_check,
        updater=app_updater,
    )
    app.run()
    if app.staged is not None and app_updater is not None:
        installed = install_update(app_updater, app.staged, app)
        if installed and app.restart_requested:
            restart(app_updater.target, sys.argv[1:] if argv is None else argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
