"""Render README screenshots (SVG) from the real app.

Default is live ESPN data, so what you capture is whatever the board looks like right now:

    .venv\\Scripts\\python scripts\\screenshots.py

``--fixtures`` renders from the saved test payloads instead, which is reproducible offline.
Output goes to ``docs/img/``. GitHub displays the SVGs inline.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cfbtui.app import CfbApp  # noqa: E402
from cfbtui.config import Config  # noqa: E402
from cfbtui.espn.client import EspnClient  # noqa: E402
from cfbtui.ui.widgets.game_card import GameCard  # noqa: E402

SIZE = (140, 44)


def make_client(fixtures: bool):
    if not fixtures:
        return EspnClient()
    sys.path.insert(0, str(ROOT))
    from tests.fakes import load_board, load_rankings
    from tests.test_screens import ScreenClient

    return ScreenClient(load_board("pairs/final_after.json"), rankings=load_rankings())


async def shot(out: Path, name: str, client, glyphs: str, keys: tuple[str, ...] = (), week: int | None = None) -> None:
    app = CfbApp(client=client, glyph_set=glyphs, week=week, config=Config())
    async with app.run_test(size=SIZE) as pilot:
        for _ in range(100):
            if len(app.query(GameCard)) > 0:
                break
            await pilot.pause(0.1)
        else:
            raise SystemExit(f"{name}: no cards appeared; is ESPN reachable?")
        for key in keys:
            await pilot.press(key)
            await pilot.pause(0.5)
        await pilot.pause(1.0)  # let the detail/rankings fetch land
        app.save_screenshot(f"{name}.svg", path=str(out))
        print("saved", out / f"{name}.svg")


async def main(fixtures: bool, out: Path, week: int | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    jobs = (
        ("grid", "nerd", ()),
        ("grid-unicode", "unicode", ()),
        ("grid-ascii", "ascii", ()),
        ("list", "nerd", ("v",)),
        ("conferences", "nerd", ("o",)),
        ("detail", "nerd", ("right", "enter")),
        ("rankings", "nerd", ("R",)),
    )
    for name, glyphs, keys in jobs:
        await shot(out, name, make_client(fixtures), glyphs, keys, week)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures", action="store_true", help="render from saved test payloads, not live ESPN")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "img")
    parser.add_argument("--week", type=int, help="capture this week, e.g. last week for finished games")
    args = parser.parse_args()
    asyncio.run(main(args.fixtures, args.out, args.week))
