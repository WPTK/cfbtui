"""Manual live spot check for the data layer. Not shipped, not a recorder.

    .venv\\Scripts\\python scripts\\spot_check.py                 # this week, FBS, 2 polls 30s apart
    .venv\\Scripts\\python scripts\\spot_check.py --polls 6 --interval 20
    .venv\\Scripts\\python scripts\\spot_check.py --date 20261017 --group 81

Fetches the scoreboard through EspnClient, feeds each poll to a GameStore and
prints every event the store emits. Run it during a live Saturday to see
touchdowns, red-zone entries and upset watches come out of real deltas.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from cfbtui.espn.client import GROUP_FBS, EspnClient
from cfbtui.state.store import GameStore
from cfbtui.state.upset import UpsetRule


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--polls", type=int, default=2)
    ap.add_argument("--interval", type=float, default=30.0, help="seconds between polls")
    ap.add_argument("--week", type=int)
    ap.add_argument("--date", help="YYYYMMDD")
    ap.add_argument("--group", type=int, default=GROUP_FBS)
    ap.add_argument("--quiet-first", action="store_true", help="silence first-sight events")
    args = ap.parse_args()

    async with EspnClient() as client:
        rankings = await client.rankings()
        store = GameStore(rule=UpsetRule(rankings), emit_on_first_sight=not args.quiet_first)
        for n in range(1, args.polls + 1):
            board = await client.scoreboard(week=args.week, date=args.date, group=args.group)
            events = store.apply_scoreboard(board)
            stamp = datetime.now().strftime("%H:%M:%S")
            live = len(store.live)
            print(f"--- poll {n} at {stamp}: {len(board.games)} games, {live} live, {len(events)} events")
            for event in events:
                print(f"    {event}")
            if n < args.polls:
                await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
