"""Opt-out check for a newer GitHub release. Never raises; any trouble means "no update"."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

import httpx

from cfbtui import __version__
from cfbtui.version import parse

RELEASES_URL = "https://api.github.com/repos/WPTK/cfbtui/releases/latest"
USER_AGENT = f"cfbtui/{__version__} (+https://github.com/WPTK/cfbtui)"


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str


def _parse(version: str) -> tuple[int, int, int]:
    text = version.strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    return parse(text)


def is_newer(candidate: str, current: str) -> bool:
    try:
        return _parse(candidate) > _parse(current)
    except (ValueError, AttributeError):
        return False


async def check_for_update(
    current: str, *, client: httpx.AsyncClient | None = None, timeout: float = 5.0
) -> UpdateInfo | None:
    own = client is None
    http = client
    try:
        if http is None:
            http = httpx.AsyncClient(follow_redirects=True)
        async with asyncio.timeout(timeout):
            resp = await http.get(
                RELEASES_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
                timeout=timeout,
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
            return None
        tag, url = data.get("tag_name"), data.get("html_url")
        if not isinstance(tag, str) or not isinstance(url, str) or not is_newer(tag, current):
            return None
        return UpdateInfo(tag.strip().lstrip("vV"), url)
    except Exception:
        return None
    finally:
        if own and http is not None:
            with contextlib.suppress(Exception):
                await http.aclose()


def update_message(info: UpdateInfo) -> str:
    return f"cfbtui {info.version} is available. Get it at {info.url}"
