"""FibVer helpers: each version component advances to the next Fibonacci number.

    python -m cfbtui.version                 # print the current version
    python -m cfbtui.version bump patch      # print what the next patch version would be
    python -m cfbtui.version bump minor --write   # rewrite cfbtui/__init__.py

Spec: https://github.com/kkokosa/fibver
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PARTS = ("major", "minor", "patch")
INIT_PATH = Path(__file__).with_name("__init__.py")
VERSION_RE = re.compile(r'^(__version__\s*=\s*")([^"]+)(")', re.MULTILINE)


def fib_next(n: int) -> int:
    """Smallest Fibonacci number strictly greater than ``n``.

    The sequence used is 0, 1, 2, 3, 5, 8, ... (the duplicate 1 is skipped,
    as FibVer suggests), so ``fib_next(0) == 1`` and ``fib_next(1) == 2``.
    """
    if n < 0:
        raise ValueError("version components are non-negative")
    if n < 1:
        return 1
    a, b = 1, 2
    while b <= n:
        a, b = b, a + b
    return b


def is_fib(n: int) -> bool:
    """True when ``n`` is a Fibonacci number (0, 1, 2, 3, 5, 8, ...)."""
    if n < 0:
        return False
    a, b = 0, 1
    while a < n:
        a, b = b, a + b
    return a == n


def parse(version: str) -> tuple[int, int, int]:
    parts = version.strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"not a MAJOR.MINOR.PATCH version: {version!r}")
    major, minor, patch = (int(p) for p in parts)
    return major, minor, patch


def is_fibver(version: str) -> bool:
    try:
        return all(is_fib(p) for p in parse(version))
    except ValueError:
        return False


def bump(version: str, part: str) -> str:
    """Return ``version`` with ``part`` advanced to the next Fibonacci number
    and every lower component reset to 0."""
    if part not in PARTS:
        raise ValueError(f"part must be one of {PARTS}, got {part!r}")
    major, minor, patch = parse(version)
    if part == "major":
        return f"{fib_next(major)}.0.0"
    if part == "minor":
        return f"{major}.{fib_next(minor)}.0"
    return f"{major}.{minor}.{fib_next(patch)}"


def read_version(path: Path = INIT_PATH) -> str:
    m = VERSION_RE.search(path.read_text(encoding="utf-8"))
    if not m:
        raise RuntimeError(f"no __version__ found in {path}")
    return m.group(2)


def write_version(version: str, path: Path = INIT_PATH) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = VERSION_RE.subn(lambda m: f"{m.group(1)}{version}{m.group(3)}", text, count=1)
    if count != 1:
        raise RuntimeError(f"no __version__ found in {path}")
    path.write_text(new_text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cfbtui.version", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("show", help="print the current version (default)")
    bump_p = sub.add_parser("bump", help="advance a component to the next Fibonacci number")
    bump_p.add_argument("part", choices=PARTS)
    bump_p.add_argument("--write", action="store_true", help="rewrite cfbtui/__init__.py")
    args = parser.parse_args(argv)

    current = read_version()
    if args.command in (None, "show"):
        print(current)
        return 0

    new = bump(current, args.part)
    if args.write:
        write_version(new)
        print(f"{current} -> {new}", file=sys.stderr)
    print(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
