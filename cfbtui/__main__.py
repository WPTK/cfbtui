"""Command-line entry point: ``python -m cfbtui`` or the ``cfbtui`` console script."""
from __future__ import annotations

import argparse

from cfbtui import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cfbtui",
        description="A colorful college football scoreboard for the terminal.",
    )
    parser.add_argument("--version", action="version", version=f"cfbtui {__version__}")
    parser.parse_args(argv)

    # Imported lazily so `--version` stays instant and never touches the terminal.
    from cfbtui.app import CfbApp

    CfbApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
