"""Command-line entry point: ``python -m cfbtui`` or the ``cfbtui`` console script.

Flags override the config file for this run only and are never written back.
"""
from __future__ import annotations

import argparse
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
    from cfbtui.espn.models import Scoreboard

    class EmptyBoard:
        async def scoreboard(self, *, week: int | None = None, group: int = 80) -> Scoreboard:
            return Scoreboard()

        async def rankings(self) -> tuple:
            return ()

    async def run() -> None:
        app = CfbApp(client=EmptyBoard(), config=Config())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()

    ZoneInfo("America/New_York")
    asyncio.run(run())
    print("selftest ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None and "--selftest" in sys.argv[1:]:
        return selftest()
    config, loaded, save_path = resolve(argv)

    # Imported lazily so `--version` stays instant and never touches the terminal.
    from cfbtui.app import CfbApp
    from cfbtui.update import check_for_update

    update_check = partial(check_for_update, __version__) if config.updates.check else None
    CfbApp(
        config=config,
        file_config=loaded.config,
        config_path=save_path,
        warnings=loaded.warnings,
        update_check=update_check,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
