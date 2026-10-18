"""Download, verify and swap in a new standalone binary. Every step takes explicit paths and clients.

Each failure raises UpdateError after removing whatever was staged; the installed binary is never
modified in place, only replaced by a rename, so it is either the old file or the new one.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

from cfbtui.update import USER_AGENT, Asset

STAGE_DIR = ".cfbtui-update"
PROBE_TIMEOUT = 60.0
RENAME_TRIES = 5
RENAME_WAIT = 0.4
STALE_LOCK = 3600.0

_SUMS_LINE = re.compile(r"^([0-9a-fA-F]{64}) [ *](\S.*)$")


class UpdateError(Exception):
    """The update could not be staged or applied; the installed binary is untouched."""


def parse_sums(text: str) -> dict[str, str]:
    """sha256sum output ("<hex>  <name>", a "*" before the name tolerated) as {name: lowercase hex}."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _SUMS_LINE.match(line.rstrip("\r"))
        if match is None:
            raise UpdateError("SHA256SUMS is malformed")
        sums[match.group(2)] = match.group(1).lower()
    return sums


def _remove(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def _lock(directory: Path) -> Path:
    lock = directory / "lock"
    with contextlib.suppress(OSError):
        if time.time() - lock.stat().st_mtime > STALE_LOCK:
            lock.unlink()
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise UpdateError("another cfbtui is already downloading an update") from None
    except OSError as exc:
        raise UpdateError(f"cannot write to {directory}: {exc.strerror or exc}") from None
    return lock


def stage(asset: Asset, sums: dict[str, str], target_dir: Path, client: httpx.Client) -> Path:
    """Download asset beside the install, verify size and sha256, and return the `.ready` file."""
    expected = sums.get(asset.name)
    if expected is None:
        raise UpdateError(f"SHA256SUMS has no line for {asset.name}")
    directory = target_dir / STAGE_DIR
    try:
        directory.mkdir(exist_ok=True)
    except OSError as exc:
        raise UpdateError(f"cannot write to {target_dir}: {exc.strerror or exc}") from None
    lock = _lock(directory)
    part = directory / (asset.name + ".part")
    ready = directory / (asset.name + ".ready")
    done = False
    try:
        digest = hashlib.sha256()
        size = 0
        with (
            client.stream("GET", asset.url, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as resp,
            open(part, "wb") as out,
        ):
            if resp.status_code != 200:
                raise UpdateError(f"download failed: HTTP {resp.status_code}")
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > asset.size:
                    raise UpdateError("download is larger than the release says")
                digest.update(chunk)
                out.write(chunk)
        if size != asset.size:
            raise UpdateError("download is smaller than the release says")
        if digest.hexdigest() != expected:
            raise UpdateError("download does not match SHA256SUMS")
        part.chmod(0o755)
        os.replace(part, ready)
        done = True
        return ready
    except UpdateError:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise UpdateError(f"download failed: {exc}") from None
    finally:
        if not done:
            _remove(part)
            _remove(ready)
        _remove(lock)
        with contextlib.suppress(OSError):
            directory.rmdir()


def probe(path: Path, version: str, run=subprocess.run) -> None:
    """Raise unless the staged binary reports `version` and passes its own selftest."""
    for args in (["--version"], ["--selftest"]):
        try:
            done = run([str(path), *args], capture_output=True, text=True, timeout=PROBE_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(f"the new version would not run: {exc}") from None
        if done.returncode != 0:
            raise UpdateError(f"the new version failed {args[0]}")
        if args[0] == "--version" and version not in (done.stdout or ""):
            raise UpdateError(f"the new version reports {(done.stdout or '').strip()!r}, not {version}")


def _rename(src: Path, dst: Path) -> None:
    """os.replace, retried on PermissionError for a few seconds (antivirus scanners hold new files)."""
    for attempt in range(RENAME_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == RENAME_TRIES - 1:
                raise
            time.sleep(RENAME_WAIT)


def apply(target: Path, staged: Path) -> None:
    """Replace target with staged by rename; on any failure target is as it was and staged is removed."""
    old = target.with_name(target.name + ".old")
    try:
        if sys.platform != "win32":
            os.replace(staged, target)
            return
        # Windows cannot overwrite or delete a running exe but can rename it out of the way.
        if old.exists():
            old.unlink()
        _rename(target, old)
        try:
            _rename(staged, target)
        except OSError:
            with contextlib.suppress(OSError):
                _rename(old, target)
            raise
    except OSError as exc:
        _remove(staged)
        raise UpdateError(f"could not install the update: {exc.strerror or exc}") from None


def cleanup_old(target: Path) -> None:
    """Delete the previous version, or restore it when a crash left only `.old` behind."""
    old = target.with_name(target.name + ".old")
    try:
        if not old.exists():
            return
        if target.exists():
            old.unlink()
        else:
            os.replace(old, target)
    except OSError:
        pass
