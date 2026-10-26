"""Download, verify and swap in a new standalone binary. Every step takes explicit paths and clients.

Each failure raises UpdateError after removing whatever was staged; the installed binary is never
modified in place, only replaced by a rename, so it is either the old file or the new one. The
staging folder is guarded by an OS lock held from `stage` until `apply` or `discard`, so only the
process that staged a file ever deletes it.
"""
from __future__ import annotations

import contextlib
import glob
import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from cfbtui.update import SUMS_NAME, USER_AGENT, Asset, UpdateInfo, asset_name, install_kind

STAGE_DIR = ".cfbtui-update"
SUMS_MAX = 1 << 20
PROBE_TIMEOUT = 60.0
RENAME_TRIES = 5
RENAME_WAIT = 0.4

_SUMS_LINE = re.compile(r"^([0-9a-fA-F]{64}) [ *](\S.*)$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class UpdateError(Exception):
    """The update could not be staged or applied; the installed binary is untouched."""


class RollbackError(UpdateError):
    """The swap failed and the previous version could not be put back; the message says how."""


def parse_sums(text: str) -> dict[str, str]:
    """sha256sum output ("<hex>  <name>", a "*" before the name tolerated) as {name: lowercase hex}."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _SUMS_LINE.match(line.rstrip("\r"))
        if match is None:
            raise UpdateError("SHA256SUMS is malformed")
        name, digest = match.group(2), match.group(1).lower()
        if sums.setdefault(name, digest) != digest:
            raise UpdateError(f"SHA256SUMS lists {name} twice with different hashes")
    return sums


def child_env() -> dict[str, str]:
    """The environment for a child cfbtui. A PyInstaller onefile parent exports _PYI_* variables that would
    make a child binary reuse the parent's (about to be replaced) extraction folder."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI_")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise UpdateError("the update was cancelled")


def _remove(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def _fsync_dir(directory: Path) -> None:
    if sys.platform == "win32":
        return
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _lock_fd(lock: Path) -> int:
    """Open lock and take an exclusive non-blocking OS lock on it; the lock dies with the process."""
    try:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR)
    except OSError as exc:
        raise UpdateError(f"cannot write to {lock.parent}: {exc.strerror or exc}") from None
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if os.fstat(fd).st_ino != os.stat(lock).st_ino:  # the holder removed it as we opened it
                raise OSError("lock file replaced")
    except OSError:
        os.close(fd)
        raise UpdateError("another cfbtui is already downloading an update") from None
    return fd


class Staged:
    """A verified download waiting beside the install. Holds the stage lock until apply or discard."""

    def __init__(self, path: Path, sha256: str, lock_fd: int):
        self.path = path
        self.sha256 = sha256
        self._fd: int | None = lock_fd

    def release(self) -> None:
        """Drop the lock and tidy the stage folder; leaves the staged file if it still exists."""
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        lock = self.path.parent / "lock"
        if sys.platform != "win32":
            _remove(lock)  # while still holding it, so nobody can lock a file we then delete
        os.close(fd)
        _remove(lock)
        with contextlib.suppress(OSError):
            self.path.parent.rmdir()

    def discard(self) -> None:
        _remove(self.path)
        self.release()


def _check_url(url: httpx.URL) -> None:
    if url.scheme == "https" or (url.scheme == "http" and url.host == "127.0.0.1"):
        return
    raise UpdateError(f"refusing to download from {url.scheme}://{url.host}")


def stage(
    asset: Asset, sums: dict[str, str], target_dir: Path, client: httpx.Client, version: str,
    cancel: threading.Event | None = None,
) -> Staged:
    """Download asset beside the install, verify size and sha256, and return it as Staged."""
    if not _SAFE_NAME.match(asset.name) or Path(asset.name).name != asset.name or asset.name in (".", ".."):
        raise UpdateError(f"unsafe asset name {asset.name!r}")
    expected = sums.get(asset.name)
    if expected is None:
        raise UpdateError(f"SHA256SUMS has no line for {asset.name}")
    try:
        _check_url(httpx.URL(asset.url))
    except httpx.InvalidURL:
        raise UpdateError("the release gave an invalid download URL") from None
    directory = target_dir / STAGE_DIR
    try:
        directory.mkdir(exist_ok=True)
    except OSError as exc:
        raise UpdateError(f"cannot write to {target_dir}: {exc.strerror or exc}") from None
    try:
        fd = _lock_fd(directory / "lock")
    except UpdateError:
        with contextlib.suppress(OSError):
            directory.rmdir()
        raise
    staged = Staged(directory / f"{asset.name}-{version}.ready", expected, fd)
    part = directory / (asset.name + ".part")
    try:
        digest = hashlib.sha256()
        size = 0
        with (
            client.stream("GET", asset.url, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as resp,
            open(part, "wb") as out,
        ):
            for hop in (*resp.history, resp):
                _check_url(hop.url)
            if resp.status_code != 200:
                raise UpdateError(f"download failed: HTTP {resp.status_code}")
            for chunk in resp.iter_bytes():
                _check_cancel(cancel)
                size += len(chunk)
                if size > asset.size:
                    raise UpdateError("download is larger than the release says")
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if size != asset.size:
            raise UpdateError("download is smaller than the release says")
        if digest.hexdigest() != expected:
            raise UpdateError("download does not match SHA256SUMS")
        part.chmod(0o755)
        _rename(part, staged.path)
        _fsync_dir(directory)
        return staged
    except BaseException as exc:
        _remove(part)
        staged.discard()
        if isinstance(exc, (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError, OSError, RuntimeError)):
            raise UpdateError(f"download failed: {exc}") from None
        raise


def probe(staged: Staged, version: str, run=subprocess.run, cancel: threading.Event | None = None) -> None:
    """Raise unless the staged binary reports `cfbtui <version>` and passes its own selftest.

    On any failure the staged file is deleted.
    """
    try:
        for args in (["--version"], ["--selftest"]):
            _check_cancel(cancel)
            try:
                done = run(
                    [str(staged.path), *args], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=PROBE_TIMEOUT, env=child_env(),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise UpdateError(f"the new version would not run: {exc}") from None
            if done.returncode != 0:
                raise UpdateError(f"the new version failed {args[0]}")
            if args[0] == "--version" and (done.stdout or "").strip() != f"cfbtui {version}":
                raise UpdateError(f"the new version reports {(done.stdout or '').strip()!r}, not {version}")
    except BaseException:
        staged.discard()
        raise


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


def _verify(staged: Staged) -> None:
    digest = hashlib.sha256()
    with open(staged.path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    if digest.hexdigest() != staged.sha256:
        raise UpdateError("the staged file changed after it was verified")


def apply(target: Path, staged: Staged) -> None:
    """Replace target with the staged file by rename; on failure target is as it was.

    The staged file is removed on every failure except RollbackError, where it is kept for recovery.
    """
    old = target.with_name(target.name + ".old")
    try:
        _verify(staged)
        if sys.platform != "win32":
            os.replace(staged.path, target)
            _fsync_dir(target.parent)
        else:
            # Windows cannot overwrite or delete a running exe but can rename it out of the way.
            if old.exists():
                try:
                    old.unlink()
                except OSError:  # the previous version is still running; park it under a name of its own
                    os.replace(old, old.with_name(f"{old.name}.{os.getpid()}-{time.monotonic_ns()}"))
            _rename(target, old)
            try:
                _rename(staged.path, target)
            except OSError as exc:
                try:
                    _rename(old, target)
                except OSError:
                    raise RollbackError(
                        f"the update failed ({exc.strerror or exc}) and the previous version could not be "
                        f"restored. It is at {old}; rename it to {target} to recover. The new version is "
                        f"at {staged.path}."
                    ) from None
                raise
    except RollbackError:
        staged.release()
        raise
    except (OSError, UpdateError) as exc:
        staged.discard()
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError(f"could not install the update: {exc.strerror or exc}") from None
    staged.release()


def cleanup_old(target: Path) -> None:
    """Delete the previous version, or restore it when a crash left only `.old` behind."""
    old = target.with_name(target.name + ".old")
    for parked in target.parent.glob(glob.escape(old.name) + ".*"):  # see apply: set aside while still running
        with contextlib.suppress(OSError):
            parked.unlink()
    try:
        if not old.exists():
            return
        if target.exists():
            old.unlink()
        else:
            os.replace(old, target)
    except OSError:
        pass


def sweep(target_dir: Path) -> None:
    """Delete a stage folder nobody is using (a download cut short by a kill). Skips one whose lock is held."""
    directory = target_dir / STAGE_DIR
    try:
        if not directory.is_dir():
            return
        fd = _lock_fd(directory / "lock")
    except (OSError, UpdateError):
        return
    for item in directory.iterdir():
        if item.name != "lock":
            _remove(item)
    Staged(directory / "lock", "", fd).release()


@dataclass
class Updater:
    """What the app needs to update this install: stage and probe a release, apply it, and close.

    `kind` and `asset_name` say what is possible here; the app never calls `stage` for a pip-type install.
    `close` (from the app's thread) cancels a stage running in another thread.
    """

    kind: str
    asset_name: str | None
    target: Path
    version: str
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=30.0))
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _procs: list = field(default_factory=list, repr=False)
    _issued: Staged | None = field(default=None, repr=False)

    @classmethod
    def detect(cls, version: str) -> Updater:
        return cls(install_kind(), asset_name(), Path(sys.executable).resolve(), version)

    def stage(self, info: UpdateInfo) -> Staged:
        """Download this platform's asset and SHA256SUMS, verify and probe it. Blocking; run in a thread."""
        by_name = {a.name: a for a in info.assets}
        asset, sums_asset = by_name.get(self.asset_name or ""), by_name.get(SUMS_NAME)
        if asset is None or sums_asset is None:
            raise UpdateError(f"the release has no {self.asset_name if asset is None else SUMS_NAME}")
        _check_cancel(self._cancel)
        sums = parse_sums(self._sums_text(sums_asset))
        staged = stage(asset, sums, self.target.parent, self.client, info.version, self._cancel)
        probe(staged, info.version, self._run, self._cancel)
        with self._lock:
            if self._cancel.is_set():  # closed while the last step ran; nobody will install this
                staged.discard()
                raise UpdateError("the update was cancelled")
            self._issued = staged
        return staged

    def _run(self, cmd, **kwargs):
        """subprocess.run, but close() can kill it."""
        with subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding=kwargs["encoding"], errors=kwargs["errors"], env=kwargs["env"],
        ) as proc:
            self._procs.append(proc)
            try:
                out, err = proc.communicate(timeout=kwargs["timeout"])
            except BaseException:
                proc.kill()
                raise
            finally:
                self._procs.remove(proc)
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)

    def _sums_text(self, sums_asset: Asset) -> str:
        try:
            _check_url(httpx.URL(sums_asset.url))
            if sums_asset.size > SUMS_MAX:
                raise UpdateError("SHA256SUMS is too large")
            with self.client.stream(
                "GET", sums_asset.url, headers={"User-Agent": USER_AGENT}, follow_redirects=True
            ) as resp:
                for hop in (*resp.history, resp):
                    _check_url(hop.url)
                if resp.status_code != 200:
                    raise UpdateError(f"could not read SHA256SUMS: HTTP {resp.status_code}")
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > SUMS_MAX:  # stop reading; a hostile server cannot make us buffer more
                        raise UpdateError("could not read SHA256SUMS: it is larger than the limit")
            return bytes(body).decode("utf-8")
        except (httpx.HTTPError, httpx.InvalidURL, UnicodeDecodeError, RuntimeError) as exc:
            raise UpdateError(f"could not read SHA256SUMS: {exc}") from None

    def apply(self, staged: Staged) -> None:
        apply(self.target, staged)

    def close(self, keep: Staged | None = None) -> None:
        """Cancel a stage in progress and free the client; discard a result nobody took (anything but `keep`)."""
        with self._lock:
            self._cancel.set()
            if self._issued is not None and self._issued is not keep:
                self._issued.discard()
        for proc in list(self._procs):
            with contextlib.suppress(Exception):
                proc.kill()
        with contextlib.suppress(Exception):
            self.client.close()
