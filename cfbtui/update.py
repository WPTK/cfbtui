"""Opt-out check for a newer GitHub release. Never raises; any trouble means "no update"."""
from __future__ import annotations

import asyncio
import contextlib
import platform as _platform
import sys
from dataclasses import dataclass

import httpx

from cfbtui import __version__
from cfbtui.version import parse

SUMS_NAME = "SHA256SUMS"  # the release asset that lists every other asset's sha256
RELEASES_URL = "https://api.github.com/repos/WPTK/cfbtui/releases/latest"
USER_AGENT = f"cfbtui/{__version__} (+https://github.com/WPTK/cfbtui)"


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    assets: tuple[Asset, ...] = ()


def _assets(data: dict) -> tuple[Asset, ...]:
    out = []
    for item in data.get("assets") if isinstance(data.get("assets"), list) else []:
        if not isinstance(item, dict):
            continue
        name, url, size = item.get("name"), item.get("browser_download_url"), item.get("size")
        if isinstance(name, str) and isinstance(url, str) and type(size) is int and size >= 0:
            out.append(Asset(name, url, size))
    return tuple(out)


def install_kind(*, frozen: bool | None = None, prefix: str | None = None) -> str:
    """One of "binary", "pipx", "uv" or "pip"; the arguments exist so tests can inject them."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))
    if frozen:
        return "binary"
    path = (sys.prefix if prefix is None else prefix).replace("\\", "/").lower()
    if "pipx/venvs" in path:
        return "pipx"
    if "uv/tools" in path:
        return "uv"
    return "pip"


def asset_name(system: str | None = None, machine: str | None = None) -> str | None:
    """Release asset for this platform (see release.yml), or None when none is published."""
    system = (_platform.system() if system is None else system).lower()
    machine = (_platform.machine() if machine is None else machine).lower()
    os_name = {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(system)
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if os_name is None or arch is None:
        return None
    return f"cfbtui-{os_name}-{arch}" + (".exe" if os_name == "windows" else "")


def pip_message(kind: str) -> str:
    command = {
        "pipx": "pipx upgrade cfbtui",
        "uv": "uv tool upgrade cfbtui",
    }.get(kind, "python -m pip install -U cfbtui")
    return f"Upgrade with: {command}"


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
        return UpdateInfo(tag.strip().lstrip("vV"), url, _assets(data))
    except Exception:
        return None
    finally:
        if own and http is not None:
            with contextlib.suppress(Exception):
                await http.aclose()


def decide(kind: str, *, auto: bool, no_config: bool, current: str, info: UpdateInfo, asset: str | None) -> str:
    """What to do about a newer release: "download" it, show the upgrade "message", or show the "link".

    Only a standalone binary downloads, and only for [updates] auto, a config file, this platform's asset in
    the release (plus its SHA256SUMS) and a minor or patch bump; a new major version is announced, never
    installed unasked.
    """
    if kind != "binary":
        return "message"
    try:
        major = _parse(info.version)[0] != _parse(current)[0]
    except ValueError:
        return "link"
    names = {a.name for a in info.assets}
    if not auto or no_config or major or asset not in names or SUMS_NAME not in names:
        return "link"
    return "download"


def update_message(info: UpdateInfo) -> str:
    return f"cfbtui {info.version} is available. Get it at {info.url}"
