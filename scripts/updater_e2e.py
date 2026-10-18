"""End-to-end test of the standalone binary updating itself. Used by .github/workflows/updater-e2e.yml.

    python scripts/updater_e2e.py OLD_BINARY NEW_BINARY OLD_VERSION NEW_VERSION WORKDIR

OLD_BINARY reports OLD_VERSION and NEW_BINARY reports NEW_VERSION. A throwaway server on 127.0.0.1 plays the
GitHub release feed (CFBTUI_RELEASES_URL) and offers NEW_BINARY with a SHA256SUMS file. Everything happens
under WORKDIR; the checkout's dist/ is never touched. Prints one line per check and exits 1 on the first failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cfbtui.update import RELEASES_URL_ENV, SUMS_NAME, asset_name

TIMEOUT = 180


def check(ok: bool, what: str) -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {what}", flush=True)
    if not ok:
        sys.exit(1)


class Feed:
    """A fake release on 127.0.0.1. `bad_sums` makes SHA256SUMS list the wrong hash."""

    def __init__(self, binary: Path, version: str) -> None:
        self.name = asset_name()
        self.data = binary.read_bytes()
        self.version = version
        self.bad_sums = False
        feed = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/releases/latest":
                    body = json.dumps(feed.release(self.server.server_port)).encode()
                elif self.path == f"/{feed.name}":
                    body = feed.data
                elif self.path == f"/{SUMS_NAME}":
                    body = feed.sums().encode()
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/releases/latest"

    def sums(self) -> str:
        digest = hashlib.sha256(self.data).hexdigest()
        if self.bad_sums:
            digest = "0" * 64
        return f"{digest}  {self.name}\n"

    def release(self, port: int) -> dict:
        base = f"http://127.0.0.1:{port}"
        return {
            "tag_name": f"v{self.version}",
            "html_url": f"{base}/release",
            "assets": [
                {"name": self.name, "browser_download_url": f"{base}/{self.name}", "size": len(self.data)},
                {"name": SUMS_NAME, "browser_download_url": f"{base}/{SUMS_NAME}", "size": len(self.sums().encode())},
            ],
        }


def run(binary: Path, feed: Feed, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, RELEASES_URL_ENV: feed.url}
    return subprocess.run(
        [str(binary), "--no-config", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=TIMEOUT, env=env, cwd=binary.parent,
    )


def fresh_install(old: Path, work: Path, name: str) -> Path:
    folder = work / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    target = folder / old.name
    shutil.copy2(old, target)
    return target


def version_of(binary: Path, feed: Feed) -> str:
    return run(binary, feed, "--version").stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def leftovers(target: Path) -> list[str]:
    return sorted(p.name for p in target.parent.iterdir() if p.name != target.name)


def main() -> None:
    old, new = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    old_version, new_version, work = sys.argv[3], sys.argv[4], Path(sys.argv[5]).resolve()
    feed = Feed(new, new_version)
    windows = sys.platform == "win32"

    print("-- update on quit, then a second run")
    target = fresh_install(old, work, "apply")
    check(version_of(target, feed) == f"cfbtui {old_version}", f"installed binary reports {old_version}")
    done = run(target, feed, "--update-test", "apply")
    check(done.returncode == 0, f"update run exits 0 ({done.stdout.strip()!r} {done.stderr.strip()!r})")
    check(f"cfbtui {new_version} installed" in done.stdout, "update run says the new version is installed")
    check(version_of(target, feed) == f"cfbtui {new_version}", f"installed binary now reports {new_version}")
    check(digest(target) == hashlib.sha256(feed.data).hexdigest(), "installed file is byte-identical to the release")
    check((target.parent / (target.name + ".old")).exists() == windows,
          "previous version kept as .old on Windows only (the new one has not started yet)")
    done = run(target, feed, "--update-test", "apply")
    check(done.returncode == 0 and f"cfbtui {new_version}: up to date" in done.stdout,
          f"second run starts and finds nothing newer ({done.stdout.strip()!r} {done.stderr.strip()!r})")
    check(leftovers(target) == [], f"second run cleaned .old and the stage folder (left: {leftovers(target)})")

    print("-- wrong checksum")
    feed.bad_sums = True
    target = fresh_install(old, work, "badsum")
    before = digest(target)
    done = run(target, feed, "--update-test", "apply")
    check(done.returncode == 1 and "does not match SHA256SUMS" in done.stderr,
          f"wrong checksum is refused ({done.stderr.strip()!r})")
    check(digest(target) == before, "installed binary is byte-identical after the refusal")
    check(version_of(target, feed) == f"cfbtui {old_version}", "installed binary still reports the old version")
    done = run(target, feed, "--update-test", "apply")  # startup sweep removes anything the failure left
    check(leftovers(target) == [], f"nothing left beside the binary (left: {leftovers(target)})")
    feed.bad_sums = False

    print("-- Restart now (install, then start the new binary)")
    target = fresh_install(old, work, "restart")
    done = run(target, feed, "--update-test", "restart")
    check(done.returncode == 0, f"restart run exits 0 ({done.stdout.strip()!r} {done.stderr.strip()!r})")
    check(f"cfbtui {new_version}: up to date" in done.stdout, "the re-executed binary started and is the new version")
    check("PyInstaller" not in done.stderr and "_PYI" not in done.stderr and "Traceback" not in done.stderr,
          f"no PyInstaller environment error ({done.stderr.strip()!r})")
    check(version_of(target, feed) == f"cfbtui {new_version}", "installed binary reports the new version")

    print("all updater e2e checks passed")


if __name__ == "__main__":
    main()
