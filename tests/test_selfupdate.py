from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from cfbtui import selfupdate
from cfbtui.selfupdate import (
    STAGE_DIR,
    RollbackError,
    Staged,
    UpdateError,
    apply,
    cleanup_old,
    parse_sums,
    probe,
    stage,
)
from cfbtui.update import Asset

NAME = "cfbtui-linux-x86_64"
PAYLOAD = b"new binary " * 5000
OLD = b"old binary"
GOOD = hashlib.sha256(PAYLOAD).hexdigest()


class Release(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/asset":
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)
        elif self.path == "/long":
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD) + 10))
            self.end_headers()
            self.wfile.write(PAYLOAD + b"x" * 10)
        elif self.path == "/cut":
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD[:1000])
            self.wfile.flush()
            self.close_connection = True
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Release)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest.fixture
def client():
    with httpx.Client() as c:
        yield c


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "cfbtui"
    path.write_bytes(OLD)
    return path


def untouched(target: Path) -> None:
    assert target.read_bytes() == OLD
    assert not (target.parent / STAGE_DIR).exists()


def asset(server, path="/asset", size=None, name=NAME):
    return Asset(name, server + path, len(PAYLOAD) if size is None else size)


def make_staged(directory: Path, data: bytes = PAYLOAD, sha: str = GOOD) -> Staged:
    """A staged file owned by the test, with the real stage lock held."""
    folder = directory / STAGE_DIR
    folder.mkdir(exist_ok=True)
    path = folder / f"{NAME}-1.2.0.ready"
    path.write_bytes(data)
    return Staged(path, sha, selfupdate._lock_fd(folder / "lock"))


def test_parse_sums_accepts_text_and_binary_marks():
    other = "b" * 64
    text = f"{GOOD.upper()}  {NAME}\n\n{other} *other file.exe\r\n{GOOD}  {NAME}\n"
    assert parse_sums(text) == {NAME: GOOD, "other file.exe": other}


@pytest.mark.parametrize(
    "text",
    ["nonsense", "abc  file", f"{GOOD} file", f"{GOOD}  ", f"{GOOD}  a\n{'1' * 64}  a"],
    ids=["junk", "short-hash", "one-space", "no-name", "duplicate-differs"],
)
def test_parse_sums_rejects_malformed(text):
    with pytest.raises(UpdateError):
        parse_sums(text)


def test_stage_downloads_verifies_and_names_the_file_by_version(server, client, target):
    staged = stage(asset(server), {NAME: GOOD}, target.parent, client, "1.2.0")
    assert staged.path.read_bytes() == PAYLOAD
    assert staged.path.name == f"{NAME}-1.2.0.ready"
    assert sorted(p.name for p in staged.path.parent.iterdir()) == [staged.path.name, "lock"]
    if sys.platform != "win32":
        assert staged.path.stat().st_mode & 0o777 == 0o755
    assert target.read_bytes() == OLD
    staged.discard()
    untouched(target)


@pytest.mark.parametrize(
    ("path", "size", "sums"),
    [
        ("/asset", len(PAYLOAD), {NAME: "0" * 64}),
        ("/asset", len(PAYLOAD), {}),
        ("/asset", len(PAYLOAD) - 1, {NAME: GOOD}),
        ("/asset", len(PAYLOAD) + 1, {NAME: GOOD}),
        ("/long", len(PAYLOAD), {NAME: GOOD}),
        ("/cut", len(PAYLOAD), {NAME: GOOD}),
        ("/missing", len(PAYLOAD), {NAME: GOOD}),
    ],
    ids=["wrong-hash", "no-line", "size-smaller", "size-larger", "overlong", "cut", "404"],
)
def test_stage_failures_leave_target_unchanged(server, client, target, path, size, sums):
    with pytest.raises(UpdateError):
        stage(asset(server, path, size), sums, target.parent, client, "1.2.0")
    untouched(target)


@pytest.mark.parametrize("name", ["../evil", "a/b", "a\\b", "", "..", "with space", "x\x00y"])
def test_stage_rejects_asset_names_that_are_not_plain_filenames(server, client, target, name):
    with pytest.raises(UpdateError, match="unsafe"):
        stage(asset(server, name=name), {name: GOOD}, target.parent, client, "1.2.0")
    untouched(target)


@pytest.mark.parametrize(
    "url", ["http://example.com/a", "ftp://example.com/a", "file:///etc/passwd", "http://[::1]:1/a"]
)
def test_stage_rejects_non_https_urls(client, target, url):
    with pytest.raises(UpdateError):
        stage(Asset(NAME, url, 1), {NAME: GOOD}, target.parent, client, "1.2.0")
    untouched(target)


def test_stage_invalid_url_is_an_update_error(client, target):
    with pytest.raises(UpdateError):
        stage(Asset(NAME, "http://127.0.0.1:99999999/a", 1), {NAME: GOOD}, target.parent, client, "1.2.0")
    untouched(target)


def test_stage_unreachable_server_is_an_update_error(client, target):
    with pytest.raises(UpdateError):
        stage(Asset(NAME, "http://127.0.0.1:9/asset", 1), {NAME: GOOD}, target.parent, client, "1.2.0")
    untouched(target)


def test_two_instances_share_the_stage_dir_without_touching_each_other(server, client, target):
    first = stage(asset(server), {NAME: GOOD}, target.parent, client, "1.2.0")
    with pytest.raises(UpdateError, match="already downloading"):
        stage(asset(server), {NAME: GOOD}, target.parent, client, "1.2.0")
    assert first.path.read_bytes() == PAYLOAD  # the loser did not delete the owner's file
    assert (first.path.parent / "lock").exists()
    first.discard()
    untouched(target)
    stage(asset(server), {NAME: GOOD}, target.parent, client, "1.2.0").discard()


def test_an_old_lock_file_is_not_treated_as_a_held_lock(server, client, target):
    folder = target.parent / STAGE_DIR
    folder.mkdir()
    (folder / "lock").write_bytes(b"")
    os.utime(folder / "lock", (1, 1))
    stage(asset(server), {NAME: GOOD}, target.parent, client, "1.2.0").discard()
    untouched(target)


def test_stage_unwritable_directory_is_a_clear_error(server, client, target, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_bytes(b"")
    with pytest.raises(UpdateError, match="cannot write"):
        stage(asset(server), {NAME: GOOD}, blocker, client, "1.2.0")
    untouched(target)


def completed(code=0, out="cfbtui 1.2.0\n"):
    return subprocess.CompletedProcess([], code, out, "")


def test_probe_runs_version_then_selftest_decoding_as_utf8(target):
    staged = make_staged(target.parent)
    calls = []

    def run(cmd, **kw):
        calls.append((cmd[1], kw["timeout"], kw["encoding"], kw["errors"]))
        return completed()

    probe(staged, "1.2.0", run)
    assert calls == [("--version", 60.0, "utf-8", "replace"), ("--selftest", 60.0, "utf-8", "replace")]
    assert staged.path.exists()
    staged.discard()


@pytest.mark.parametrize(
    "run",
    [
        lambda cmd, **kw: completed(1),
        lambda cmd, **kw: completed(out="cfbtui 0.9.0\n"),
        lambda cmd, **kw: completed(out="not cfbtui 1.2.0 at all\n"),
        lambda cmd, **kw: completed(0 if cmd[1] == "--version" else 3),
        lambda cmd, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd, 60)),
        lambda cmd, **kw: (_ for _ in ()).throw(OSError("bad exe")),
    ],
    ids=["exit-1", "wrong-version", "substring-version", "selftest-fails", "timeout", "oserror"],
)
def test_failed_probe_deletes_the_staged_file_and_folder(target, run):
    staged = make_staged(target.parent)
    with pytest.raises(UpdateError):
        probe(staged, "1.2.0", run)
    assert not staged.path.exists()
    untouched(target)


def test_probe_runs_a_real_file_under_a_dotted_ready_name(target):
    folder = target.parent / STAGE_DIR
    folder.mkdir()
    path = folder / "cfbtui-windows-x86_64.exe-1.2.0.ready"
    env = None
    if sys.platform == "win32":
        base = Path(sys._base_executable).parent
        shutil.copy(base / "python.exe", path)
        for dll in base.glob("*.dll"):
            shutil.copy(dll, folder / dll.name)
        env = {"PYTHONHOME": sys.base_prefix}
    else:
        path.write_text('#!/bin/sh\necho "cfbtui 1.2.0"\n')
        path.chmod(0o755)
    staged = Staged(path, GOOD, selfupdate._lock_fd(folder / "lock"))

    def run(cmd, **kw):  # the copied interpreter ignores our flags and prints what cfbtui would
        if env is None:
            return subprocess.run(cmd, **kw)
        return subprocess.run([cmd[0], "-c", "print('cfbtui 1.2.0')"], **{**kw, "env": {**kw["env"], **env}})

    probe(staged, "1.2.0", run)
    assert path.exists()
    staged.release()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX swap")
def test_apply_swaps_by_replace_on_posix(target, tmp_path):
    inode = target.stat().st_ino
    staged = make_staged(tmp_path)
    apply(target, staged)
    assert target.read_bytes() == PAYLOAD
    assert not target.with_name("cfbtui.old").exists()
    assert target.stat().st_ino != inode
    assert not (tmp_path / STAGE_DIR).exists()


@pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="needs POSIX permissions as a non-root user",
)
def test_apply_into_a_read_only_directory_fails_and_cleans_up(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    target = install / "cfbtui"
    target.write_bytes(OLD)
    other = tmp_path / "other"
    other.mkdir()
    staged = make_staged(other)
    install.chmod(0o555)
    try:
        with pytest.raises(UpdateError):
            apply(target, staged)
    finally:
        install.chmod(0o755)
    assert target.read_bytes() == OLD
    assert not staged.path.exists()


def test_apply_refuses_a_staged_file_that_changed_after_verification(target, tmp_path):
    staged = make_staged(tmp_path, data=PAYLOAD + b"tampered")
    with pytest.raises(UpdateError, match="changed"):
        apply(target, staged)
    assert target.read_bytes() == OLD
    assert not staged.path.exists()


def test_cleanup_old_deletes_old_and_restores_when_only_old(target):
    old = target.with_name("cfbtui.old")
    old.write_bytes(b"older")
    cleanup_old(target)
    assert not old.exists()
    assert target.read_bytes() == OLD
    target.unlink()
    old.write_bytes(b"older")
    cleanup_old(target)
    assert target.read_bytes() == b"older"
    cleanup_old(target)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _create = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    _create.restype = wintypes.HANDLE
    _create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _close = ctypes.WinDLL("kernel32").CloseHandle
    READ, SHARE_READ, SHARE_DELETE, OPEN_EXISTING = 0x80000000, 1, 4, 3

    class Held:
        """Open a file the way a running exe or a scanner does, for the given share mode."""

        def __init__(self, path: Path, share: int):
            self.handle = _create(str(path), READ, share, None, OPEN_EXISTING, 0, None)
            assert self.handle != wintypes.HANDLE(-1).value

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            _close(self.handle)


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(selfupdate, "RENAME_WAIT", 0.01)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file locking")
def test_apply_renames_a_running_exe_out_of_the_way(target, tmp_path, fast):
    staged = make_staged(tmp_path)
    with Held(target, SHARE_READ | SHARE_DELETE):  # like a running image: renamable, not writable
        with pytest.raises(PermissionError), open(target, "r+b"):
            pass
        apply(target, staged)
        assert target.read_bytes() == PAYLOAD
        assert target.with_name("cfbtui.old").read_bytes() == OLD
    cleanup_old(target)
    assert not target.with_name("cfbtui.old").exists()
    assert target.read_bytes() == PAYLOAD
    assert not (tmp_path / STAGE_DIR).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file locking")
def test_apply_with_a_locked_old_fails_and_changes_nothing(target, tmp_path, fast):
    old = target.with_name("cfbtui.old")
    old.write_bytes(b"locked")
    staged = make_staged(tmp_path)
    with Held(old, SHARE_READ), pytest.raises(UpdateError):
        apply(target, staged)
    assert target.read_bytes() == OLD
    assert old.read_bytes() == b"locked"
    assert not staged.path.exists()
    with Held(old, SHARE_READ):
        cleanup_old(target)  # tolerated
    assert old.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file locking")
def test_apply_rolls_back_when_the_staged_file_is_locked(target, tmp_path, fast):
    staged = make_staged(tmp_path)
    # a scanner holding the new file: it cannot be renamed
    with Held(staged.path, SHARE_READ), pytest.raises(UpdateError):
        apply(target, staged)
    assert target.read_bytes() == OLD
    assert not target.with_name("cfbtui.old").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file locking")
def test_a_failed_rollback_keeps_the_staged_file_and_names_the_old_one(target, tmp_path, fast, monkeypatch):
    staged = make_staged(tmp_path)
    old = target.with_name("cfbtui.old")
    real = selfupdate._rename
    calls = []
    holds = contextlib.ExitStack()

    def rename(src, dst):
        real(src, dst)
        if not calls:  # after the first rename, hold .old and the staged file so nothing else can move
            holds.enter_context(Held(old, SHARE_READ))
            holds.enter_context(Held(staged.path, SHARE_READ))
        calls.append((src, dst))

    monkeypatch.setattr(selfupdate, "_rename", rename)
    with holds, pytest.raises(RollbackError) as err:
        apply(target, staged)
    assert str(old) in str(err.value)
    assert "rename it" in str(err.value)
    assert old.read_bytes() == OLD
    assert staged.path.read_bytes() == PAYLOAD
    assert not target.exists()
    cleanup_old(target)
    assert target.read_bytes() == OLD


@pytest.mark.skipif(sys.platform != "win32", reason="Windows rename sequence")
def test_a_crash_between_the_two_renames_is_recovered_from_old(target, tmp_path, monkeypatch):
    staged = make_staged(tmp_path)
    real = selfupdate._rename
    calls = []

    def rename(src, dst):
        if calls:
            raise KeyboardInterrupt  # the process dies after target became .old
        calls.append(src)
        real(src, dst)

    monkeypatch.setattr(selfupdate, "_rename", rename)
    with pytest.raises(KeyboardInterrupt):
        apply(target, staged)
    assert not target.exists()
    cleanup_old(target)
    assert target.read_bytes() == OLD
    staged.discard()



# --- cancelling, sweeping, the child environment, a running .old -------------------------


def test_stage_stops_and_cleans_up_when_cancelled_mid_download(target):
    cancel = threading.Event()

    def chunks():
        yield PAYLOAD[:1000]
        cancel.set()
        yield PAYLOAD[1000:]

    def handler(request):
        return httpx.Response(200, headers={"Content-Length": str(len(PAYLOAD))}, content=chunks())

    big = Asset(NAME, "https://example.test/a", len(PAYLOAD))
    with httpx.Client(transport=httpx.MockTransport(handler)) as mock, pytest.raises(UpdateError, match="cancelled"):
        stage(big, {NAME: GOOD}, target.parent, mock, "1.2.0", cancel)
    untouched(target)


def test_probe_checks_for_cancellation_between_steps_and_discards(target):
    staged = make_staged(target.parent)
    cancel = threading.Event()

    def run(cmd, **kw):
        cancel.set()
        return completed()

    with pytest.raises(UpdateError, match="cancelled"):
        probe(staged, "1.2.0", run, cancel)
    assert not staged.path.exists()


def test_probe_passes_a_clean_pyinstaller_environment(target, monkeypatch):
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "/old")
    staged = make_staged(target.parent)
    envs = []

    def run(cmd, **kw):
        envs.append(kw["env"])
        return completed()

    probe(staged, "1.2.0", run)
    assert envs and all("_PYI_ARCHIVE_FILE" not in e and e["PYINSTALLER_RESET_ENVIRONMENT"] == "1" for e in envs)
    staged.discard()


def test_sweep_deletes_an_abandoned_stage_folder(target):
    folder = target.parent / STAGE_DIR
    folder.mkdir()
    (folder / "x.part").write_bytes(b"half")
    (folder / "x.ready").write_bytes(b"done")
    (folder / "lock").write_bytes(b"")
    selfupdate.sweep(target.parent)
    assert not folder.exists() and target.read_bytes() == OLD


def test_sweep_leaves_a_folder_whose_lock_is_held(target):
    staged = make_staged(target.parent)
    selfupdate.sweep(target.parent)
    assert staged.path.read_bytes() == PAYLOAD
    staged.discard()


def test_sweep_ignores_a_missing_folder(target):
    selfupdate.sweep(target.parent)
    selfupdate.sweep(target.parent / "nowhere")


def test_apply_parks_a_previous_version_that_is_still_running(target, tmp_path, monkeypatch):
    old = target.with_name("cfbtui.old")
    old.write_bytes(b"still running")
    staged = make_staged(tmp_path)
    real = Path.unlink

    def unlink(self, *args, **kwargs):
        if self.name == "cfbtui.old":
            raise PermissionError("in use")
        return real(self, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(sys, "platform", "win32")
        m.setattr(Path, "unlink", unlink)
        apply(target, staged)
    assert target.read_bytes() == PAYLOAD
    assert old.read_bytes() == OLD  # the version just replaced
    (parked,) = list(tmp_path.glob("cfbtui.old.*"))
    assert parked.read_bytes() == b"still running"
    cleanup_old(target)
    assert not old.exists() and not parked.exists()
