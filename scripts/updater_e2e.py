"""End-to-end test of the standalone binary updating itself. Used by .github/workflows/updater-e2e.yml.

    python scripts/updater_e2e.py embed-key KEYFILE
    python scripts/updater_e2e.py OLD_BINARY NEW_BINARY OLD_VERSION NEW_VERSION WORKDIR KEYFILE

`embed-key` runs first, in the scratch checkout the binaries are built from (never in a commit): it makes a
throwaway Ed25519 key, saves its seed at KEYFILE and writes the public half into cfbtui/sigverify.py as the
current release key, so the binaries built next trust it. The real private key is never involved.

OLD_BINARY reports OLD_VERSION and NEW_BINARY reports NEW_VERSION. A throwaway server on 127.0.0.1 plays the
GitHub release feed (CFBTUI_RELEASES_URL) and offers NEW_BINARY with a SHA256SUMS file signed by KEYFILE's key
(SHA256SUMS.sig). Everything happens under WORKDIR; the checkout's dist/ is never touched. Prints one line per
check and exits 1 on the first failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sign_sums

from cfbtui.update import RELEASES_URL_ENV, SIG_NAME, SUMS_NAME, asset_name

TIMEOUT = 180
SIGVERIFY = Path(__file__).resolve().parent.parent / "cfbtui" / "sigverify.py"


def check(ok: bool, what: str) -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {what}", flush=True)
    if not ok:
        sys.exit(1)


def embed_key(keyfile: Path) -> None:
    """Make a throwaway signing key and trust it in this checkout's cfbtui/sigverify.py."""
    sign_sums.keygen(keyfile)
    pub = sign_sums.b64(sign_sums.public_key(sign_sums.read_seed(keyfile)))
    patched, count = re.subn(
        r'(?m)^KEY_CURRENT = ".*"$', f'KEY_CURRENT = "{pub}"', SIGVERIFY.read_text(encoding="utf-8")
    )
    if count != 1:
        sys.exit("could not find the KEY_CURRENT line in cfbtui/sigverify.py")
    SIGVERIFY.write_text(patched, encoding="utf-8", newline="\n")
    print(f"trusting the throwaway key {pub} in {SIGVERIFY}")


class Feed:
    """A fake release on 127.0.0.1. `mode` says what is wrong with it, if anything:

    "good"         SHA256SUMS signed by the trusted throwaway key
    "bad_sums"     SHA256SUMS lists the wrong hash for the binary, and the signature covers that wrong list
    "forged_sums"  SHA256SUMS changed after it was signed (the hash is right; only the signature is wrong)
    "wrong_key"    signed by a key the binaries do not trust
    "no_sig"       no SHA256SUMS.sig asset at all
    """

    def __init__(self, binary: Path, version: str, seed: bytes) -> None:
        self.name = asset_name()
        self.data = binary.read_bytes()
        self.version = version
        self.seed = seed
        self.mode = "good"
        feed = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/releases/latest":
                    body = json.dumps(feed.release(self.server.server_port)).encode()
                elif self.path == f"/{feed.name}":
                    body = feed.data
                elif self.path == f"/{SUMS_NAME}":
                    body = feed.sums()
                elif self.path == f"/{SIG_NAME}" and feed.mode != "no_sig":
                    body = feed.sig()
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

    def sums(self, as_signed: bool = False) -> bytes:
        """The manifest served; `as_signed` is the manifest the signature was made over."""
        digest = hashlib.sha256(self.data).hexdigest()
        if self.mode == "bad_sums":
            digest = "0" * 64
        text = f"{digest}  {self.name}\n"
        if self.mode == "forged_sums" and not as_signed:
            text += f"{'0' * 64}  cfbtui-extra\n"
        return text.encode()

    def sig(self) -> bytes:
        seed = bytes(32) if self.mode == "wrong_key" else self.seed
        return (sign_sums.b64(sign_sums.sign(seed, self.sums(as_signed=True))) + "\n").encode()

    def release(self, port: int) -> dict:
        base = f"http://127.0.0.1:{port}"
        assets = [
            {"name": self.name, "browser_download_url": f"{base}/{self.name}", "size": len(self.data)},
            {"name": SUMS_NAME, "browser_download_url": f"{base}/{SUMS_NAME}", "size": len(self.sums())},
        ]
        if self.mode != "no_sig":
            assets.append({"name": SIG_NAME, "browser_download_url": f"{base}/{SIG_NAME}", "size": len(self.sig())})
        return {"tag_name": f"v{self.version}", "html_url": f"{base}/release", "assets": assets}


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
    if len(sys.argv) == 3 and sys.argv[1] == "embed-key":
        embed_key(Path(sys.argv[2]))
        return
    if len(sys.argv) != 7:
        sys.exit(__doc__)
    old, new = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    old_version, new_version, work = sys.argv[3], sys.argv[4], Path(sys.argv[5]).resolve()
    feed = Feed(new, new_version, sign_sums.read_seed(Path(sys.argv[6])))
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

    refusals = [
        ("bad_sums", 1, "does not match SHA256SUMS", "a wrong checksum in a signed manifest"),
        ("forged_sums", 1, "signature check failed", "a manifest changed after it was signed"),
        ("wrong_key", 1, "signature check failed", "a manifest signed by an untrusted key"),
        ("no_sig", 2, "would not be downloaded", "a release with no signature file"),
    ]
    for mode, code, message, what in refusals:
        print(f"-- {what}")
        feed.mode = mode
        target = fresh_install(old, work, mode)
        before = digest(target)
        done = run(target, feed, "--update-test", "apply")
        check(done.returncode == code and message in done.stderr, f"refused ({done.stderr.strip()!r})")
        check(digest(target) == before, "installed binary is byte-identical after the refusal")
        check(version_of(target, feed) == f"cfbtui {old_version}", "installed binary still reports the old version")
        done = run(target, feed, "--update-test", "apply")  # startup sweep removes anything the failure left
        check(leftovers(target) == [], f"nothing left beside the binary (left: {leftovers(target)})")
    feed.mode = "good"

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
