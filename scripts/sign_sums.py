"""Make and use the offline Ed25519 release signing key. See docs/release-signing.md.

    python scripts/sign_sums.py keygen KEYFILE        make a key pair; writes the private seed, prints the public key
    python scripts/sign_sums.py pubkey KEYFILE        print the public key for a seed file
    python scripts/sign_sums.py sign KEYFILE SUMS     write SUMS.sig (base64 of the raw 64-byte signature)
    python scripts/sign_sums.py verify SUMS SIG       check SUMS against the keys built into cfbtui/sigverify.py

This script never stores a key anywhere but the file you name, refuses to write one inside a git checkout and
needs no package beyond the standard library. `sign` refuses to sign with a key the build does not trust, so a
wrong key file is caught before a release goes out. Signing is the textbook RFC 8032 algorithm, run on a small
file by hand a few times a year; speed and side channels do not matter here.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cfbtui import sigverify


def _encode(point: tuple[int, int, int, int]) -> bytes:
    zinv = sigverify._inv(point[2])
    x, y = point[0] * zinv % sigverify._P, point[1] * zinv % sigverify._P
    return (y | (x & 1) << 255).to_bytes(32, "little")


def _expand(seed: bytes) -> tuple[int, bytes, bytes]:
    h = hashlib.sha512(seed).digest()
    secret = int.from_bytes(h[:32], "little")
    secret &= (1 << 254) - 8
    secret |= 1 << 254
    return secret, h[32:], _encode(sigverify._mul(secret, sigverify._BASE))


def public_key(seed: bytes) -> bytes:
    return _expand(seed)[2]


def sign(seed: bytes, message: bytes) -> bytes:
    """The RFC 8032 signature of `message`: 64 raw bytes."""
    secret, prefix, pub = _expand(seed)
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % sigverify._Q
    point_r = _encode(sigverify._mul(r, sigverify._BASE))
    k = int.from_bytes(hashlib.sha512(point_r + pub + message).digest(), "little") % sigverify._Q
    return point_r + ((r + k * secret) % sigverify._Q).to_bytes(32, "little")


def read_seed(path: Path) -> bytes:
    try:
        seed = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
    except (OSError, ValueError):
        sys.exit(f"cannot read a key from {path}: expected one line of base64")
    if len(seed) != 32:
        sys.exit(f"{path} holds {len(seed)} bytes, not a 32-byte seed")
    return seed


def inside_git_checkout(path: Path) -> bool:
    return any((folder / ".git").exists() for folder in (path.resolve().parent, *path.resolve().parent.parents))


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def keygen(path: Path) -> None:
    if inside_git_checkout(path):
        sys.exit(f"{path} is inside a git checkout; put the private key on offline storage instead")
    seed = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never overwrites a key
    except OSError as exc:
        sys.exit(f"cannot create {path}: {exc.strerror or exc}")
    with os.fdopen(fd, "w", encoding="ascii") as out:
        out.write(b64(seed) + "\n")
    print(f"private seed written to {path}; back it up, never commit it, never paste it anywhere")
    print(f"public key: {b64(public_key(seed))}")


def sign_file(key_path: Path, sums_path: Path) -> None:
    seed = read_seed(key_path)
    pub = b64(public_key(seed))
    if pub not in sigverify.PUBLIC_KEYS:
        sys.exit(f"public key {pub} is not one of the keys built into cfbtui/sigverify.py; not signing")
    message = sums_path.read_bytes()
    signature = sign(seed, message)
    if not sigverify.verify(base64.b64decode(pub), message, signature):
        sys.exit("internal error: the new signature does not verify")
    out = sums_path.with_name(sums_path.name + ".sig")
    out.write_text(b64(signature) + "\n", encoding="ascii", newline="\n")
    print(f"wrote {out}")


def main(argv: list[str]) -> None:
    match argv:
        case ["keygen", key]:
            keygen(Path(key))
        case ["pubkey", key]:
            print(b64(public_key(read_seed(Path(key)))))
        case ["sign", key, sums]:
            sign_file(Path(key), Path(sums))
        case ["verify", sums, sig]:
            try:
                sigverify.verify_manifest(Path(sums).read_bytes(), Path(sig).read_bytes())
            except sigverify.SignatureError as exc:
                sys.exit(f"FAIL: {exc}")
            print("ok: SHA256SUMS is signed by a trusted key")
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
