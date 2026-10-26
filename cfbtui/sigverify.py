"""Check the Ed25519 signature on a release's SHA256SUMS, in pure Python (RFC 8032), with no new dependency.

The updater trusts a download only if SHA256SUMS carries a valid signature from one of the keys below. The
private keys stay offline with the owner (docs/release-signing.md), so someone who can only publish a GitHub
release cannot make an install pass.

Signature file format (`SHA256SUMS.sig`): the raw 64-byte Ed25519 signature, base64 encoded, on one line. It is
signed over the exact bytes of SHA256SUMS (Ed25519 hashes the whole message itself; there is no pre-hash).
Plain base64 is easy to produce and inspect with standard tools; it is not minisign's format.

Both keys are 32-byte public keys in base64. The first is the signing key; the second is an offline spare that
is never used for routine releases, so a lost or leaked first key can be replaced by a release signed with the
spare. A value that is not a valid key (the placeholders below) is ignored, and with no valid key every
verification fails: an unfinished build can never trust a manifest.
"""
from __future__ import annotations

import base64
import binascii
import hashlib

# REPLACE both with the output of `python scripts/sign_sums.py keygen` (docs/release-signing.md). The release
# workflow refuses to run while either is still a placeholder.
KEY_CURRENT = "PLACEHOLDER-signing-key-not-set"
KEY_SPARE = "PLACEHOLDER-spare-key-not-set"
PUBLIC_KEYS = (KEY_CURRENT, KEY_SPARE)

SIG_MAX = 1024  # bytes of SHA256SUMS.sig the updater will read; a real one is 88

_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


class SignatureError(Exception):
    """The manifest signature is missing, malformed or not from a trusted key. The message says which."""


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _add(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Edwards addition in extended coordinates (a = -1; complete, so it also doubles)."""
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    pa = (y1 - x1) * (y2 - x2) % _P
    pb = (y1 + x1) * (y2 + x2) % _P
    pc = 2 * t1 * t2 * _D % _P
    pd = 2 * z1 * z2 % _P
    e, f, g, h = pb - pa, pd - pc, pd + pc, pb + pa
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _mul(scalar: int, point: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    result = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _decode(data: bytes) -> tuple[int, int, int, int] | None:
    """The curve point a 32-byte encoding names, or None for a non-canonical or invalid one."""
    value = int.from_bytes(data, "little")
    sign, y = value >> 255, value & ((1 << 255) - 1)
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if x == 0 and sign:
        return None
    if x & 1 != sign:
        x = _P - x
    return x, y, 1, x * y % _P


def _same(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


_BASE_Y = 4 * _inv(5) % _P
_BASE = _decode(_BASE_Y.to_bytes(32, "little"))  # the encoding of y with an even x
assert _BASE is not None


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 Ed25519 verification. False for any malformed key or signature, never an exception."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    point_a, point_r = _decode(public_key), _decode(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if point_a is None or point_r is None or s >= _Q:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % _Q
    return _same(_mul(s, _BASE), _add(point_r, _mul(h, point_a)))


def decode_keys(values: tuple[str, ...] = PUBLIC_KEYS) -> list[bytes]:
    """The usable keys among `values`: base64 of exactly 32 bytes that form a curve point. Others are skipped."""
    keys = []
    for value in values:
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            continue
        if len(raw) == 32 and _decode(raw) is not None:
            keys.append(raw)
    return keys


def decode_signature(text: bytes | str) -> bytes:
    """The 64 signature bytes from a SHA256SUMS.sig body (base64, surrounding whitespace allowed)."""
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise SignatureError("SHA256SUMS.sig is not valid base64") from None
    if len(raw) != 64:
        raise SignatureError(f"SHA256SUMS.sig holds {len(raw)} bytes, not a 64-byte Ed25519 signature")
    return raw


def verify_manifest(manifest: bytes, signature_body: bytes | str, keys: tuple[str, ...] = PUBLIC_KEYS) -> None:
    """Raise SignatureError unless `manifest` carries a valid signature from one of `keys`.

    With no usable key at all it raises, so a build whose keys were never filled in rejects everything.
    """
    usable = decode_keys(keys)
    if not usable:
        raise SignatureError("this build has no release signing key, so it cannot verify an update")
    signature = decode_signature(signature_body)
    if not any(verify(key, manifest, signature) for key in usable):
        raise SignatureError("SHA256SUMS is not signed by a key this version trusts")
