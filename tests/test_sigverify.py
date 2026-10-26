"""Ed25519 verification of the release manifest, and the updater's use of it. No network."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import subprocess
from pathlib import Path

import httpx
import pytest

from cfbtui import sigverify
from cfbtui.selfupdate import UpdateError, Updater
from cfbtui.sigverify import SignatureError, verify, verify_manifest
from cfbtui.update import Asset, UpdateInfo

_spec = importlib.util.spec_from_file_location("sign_sums", Path(__file__).parent.parent / "scripts" / "sign_sums.py")
sign_sums = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sign_sums)

# RFC 8032 section 7.1, tests 1 and 2: (secret seed, public key, message, signature).
RFC_VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46b"
        "d25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c"
        "387b2eaeb4302aeeb00d291612bb0c00",
    ),
]
GROUP_ORDER = sigverify._Q


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.mark.parametrize(("seed", "pub", "msg", "sig"), RFC_VECTORS)
def test_rfc8032_vectors_verify_and_the_signer_reproduces_them(seed, pub, msg, sig):
    seed, pub, msg, sig = (bytes.fromhex(x) for x in (seed, pub, msg, sig))
    assert verify(pub, msg, sig)
    assert sign_sums.public_key(seed) == pub
    assert sign_sums.sign(seed, msg) == sig


@pytest.mark.parametrize(("seed", "pub", "msg", "sig"), RFC_VECTORS)
def test_tampering_with_message_signature_or_key_fails(seed, pub, msg, sig):
    pub, msg, sig = bytes.fromhex(pub), bytes.fromhex(msg), bytes.fromhex(sig)
    assert not verify(pub, msg + b"x", sig)
    for i in (0, 31, 32, 63):
        bad = bytearray(sig)
        bad[i] ^= 1
        assert not verify(pub, msg, bytes(bad))
    other = bytes.fromhex(RFC_VECTORS[1 - RFC_VECTORS.index((seed, pub.hex(), msg.hex(), sig.hex()))][1])
    assert not verify(other, msg, sig)


def test_malformed_inputs_are_false_never_exceptions():
    pub, msg, sig = (bytes.fromhex(x) for x in RFC_VECTORS[0][1:])
    assert not verify(pub[:31], msg, sig)
    assert not verify(pub, msg, sig[:63])
    assert not verify(pub, msg, sig + b"\0")
    assert not verify(b"\xff" * 32, msg, sig)  # y >= p: not a point
    assert not verify(pub, msg, sig[:32] + b"\xff" * 32)  # S >= group order
    s_plus_order = (int.from_bytes(sig[32:], "little") + GROUP_ORDER).to_bytes(32, "little")
    assert not verify(pub, msg, sig[:32] + s_plus_order)  # malleable twin of a good signature
    assert not verify(b"\0" * 32, msg, b"\0" * 64)


def test_placeholder_keys_verify_nothing():
    _, msg, sig = (bytes.fromhex(x) for x in RFC_VECTORS[0][1:])
    placeholders = ("PLACEHOLDER-signing-key-not-set", "PLACEHOLDER-spare-key-not-set", "", "AAAA")
    assert sigverify.decode_keys(placeholders) == []
    with pytest.raises(SignatureError, match="no release signing key"):
        verify_manifest(msg, b64(sig), keys=placeholders)


def test_the_shipped_keys_are_all_placeholders_or_two_distinct_real_keys():
    """Fail closed while unfinished, and never half-finished: a lone or repeated key would leave no spare."""
    keys = sigverify.decode_keys()
    assert not keys or (len(keys) == len(set(keys)) == len(sigverify.PUBLIC_KEYS) == 2)


@pytest.mark.parametrize(
    "point",
    [
        bytes([1]) + bytes(31),  # the identity (0, 1)
        bytes([0xEC]) + bytes([0xFF] * 30) + bytes([0x7F]),  # y = p - 1: (0, -1), order 2
        bytes(32),  # y = 0: order 4
    ],
    ids=["identity", "order-2", "order-4"],
)
def test_small_order_keys_are_not_keys_and_accept_no_forgery(point):
    assert sigverify.decode_keys((b64(point),)) == []
    forged = point + bytes(32)  # R = the same point, S = 0
    assert not verify(point, b"anything", forged)
    with pytest.raises(SignatureError, match="no release signing key"):
        verify_manifest(b"anything", b64(forged), keys=(b64(point),))


def test_either_embedded_key_can_sign_and_a_third_cannot():
    msg = b"abc  file\n"
    keys = tuple(b64(sign_sums.public_key(bytes([n]) * 32)) for n in (1, 2))
    for n in (1, 2):
        verify_manifest(msg, b64(sign_sums.sign(bytes([n]) * 32, msg)) + "\n", keys=keys)
    with pytest.raises(SignatureError, match="not signed by a key"):
        verify_manifest(msg, b64(sign_sums.sign(bytes([3]) * 32, msg)), keys=keys)


@pytest.mark.parametrize(
    ("body", "message"),
    [("", "64-byte"), ("not base64!", "base64"), (b64(b"x" * 63), "63 bytes"), (b64(b"x" * 65), "65 bytes")],
)
def test_malformed_signature_files_are_named(body, message):
    keys = (b64(sign_sums.public_key(b"\1" * 32)),)
    with pytest.raises(SignatureError, match=message):
        verify_manifest(b"m", body, keys=keys)


def test_signing_refuses_a_manifest_that_does_not_match_the_files_beside_it(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"one")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{hashlib.sha256(b'one').hexdigest()}  a.bin\n", encoding="utf-8")
    assert sign_sums.files_match_manifest(sums) == []
    (tmp_path / "a.bin").write_bytes(b"swapped")
    assert "a.bin does not match its hash" in sign_sums.files_match_manifest(sums)
    (tmp_path / "a.bin").write_bytes(b"one")
    (tmp_path / "extra.bin").write_bytes(b"x")
    assert "extra.bin is here but not listed" in sign_sums.files_match_manifest(sums)
    (tmp_path / "extra.bin").unlink()
    sums.write_text(sums.read_text() + f"{'0' * 64}  gone.bin\n", encoding="utf-8")
    assert "gone.bin is listed but not in" in sign_sums.files_match_manifest(sums)[0]


# --- the updater: signature first, binary last ---------------------------------------------

NAME = "cfbtui-linux-x86_64"
SEED = b"\7" * 32
OTHER_SEED = bytes([8]) * 32
PAYLOAD = b"#!/bin/sh\necho cfbtui 9.9.9\n"


class Release:
    """A fake release on a mock transport that records which URLs were requested."""

    def __init__(self, tmp_path, monkeypatch, *, seed=SEED, sums=None, sig=None):
        self.requested: list[str] = []
        digest = hashlib.sha256(PAYLOAD).hexdigest()
        self.sums = sums if sums is not None else f"{digest}  {NAME}\n".encode()
        self.sig = sig if sig is not None else b64(sign_sums.sign(seed, self.sums)).encode()
        self.files = {NAME: PAYLOAD, "SHA256SUMS": self.sums, "SHA256SUMS.sig": self.sig}
        monkeypatch.setattr(
            "cfbtui.selfupdate.verify_manifest",
            lambda manifest, body: verify_manifest(manifest, body, keys=(b64(sign_sums.public_key(SEED)),)),
        )

        def handler(request: httpx.Request) -> httpx.Response:
            self.requested.append(request.url.path.lstrip("/"))
            body = self.files.get(request.url.path.lstrip("/"))
            return httpx.Response(404) if body is None else httpx.Response(200, content=body)

        self.updater = Updater(
            "binary", NAME, tmp_path / NAME, "9.9.8", httpx.Client(transport=httpx.MockTransport(handler))
        )
        self.updater._run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "cfbtui 9.9.9\n", "")
        self.info = UpdateInfo(
            "9.9.9", "https://example.test/r",
            tuple(Asset(n, f"https://example.test/{n}", len(b)) for n, b in self.files.items()),
        )


def test_a_validly_signed_release_stages(tmp_path, monkeypatch):
    release = Release(tmp_path, monkeypatch)
    staged = release.updater.stage(release.info)
    assert staged.path.read_bytes() == PAYLOAD
    assert release.requested.index("SHA256SUMS.sig") < release.requested.index(NAME)
    assert release.requested.index("SHA256SUMS") < release.requested.index(NAME)
    staged.discard()


def test_signature_by_an_untrusted_key_is_refused_before_the_binary_is_requested(tmp_path, monkeypatch):
    release = Release(tmp_path, monkeypatch, seed=OTHER_SEED)
    with pytest.raises(UpdateError, match=r"signature check failed.*not signed by a key"):
        release.updater.stage(release.info)
    assert NAME not in release.requested and not (tmp_path / ".cfbtui-update").exists()


def test_sums_changed_after_signing_is_refused_before_the_binary_is_requested(tmp_path, monkeypatch):
    good = Release(tmp_path, monkeypatch)
    forged = hashlib.sha256(b"evil").hexdigest() + f"  {NAME}\n"
    release = Release(tmp_path, monkeypatch, sums=forged.encode(), sig=good.sig)
    with pytest.raises(UpdateError, match="signature check failed"):
        release.updater.stage(release.info)
    assert NAME not in release.requested


def test_a_garbled_signature_file_is_named(tmp_path, monkeypatch):
    release = Release(tmp_path, monkeypatch, sig=b"garbage!")
    with pytest.raises(UpdateError, match=r"SHA256SUMS\.sig is not valid base64"):
        release.updater.stage(release.info)
    assert NAME not in release.requested


def test_a_correctly_signed_manifest_still_has_to_match_the_binary(tmp_path, monkeypatch):
    sums = f"{hashlib.sha256(b'other').hexdigest()}  {NAME}\n".encode()
    release = Release(tmp_path, monkeypatch, sums=sums)
    with pytest.raises(UpdateError, match="does not match SHA256SUMS"):
        release.updater.stage(release.info)


def test_a_build_with_placeholder_keys_refuses_every_update(tmp_path, monkeypatch):
    release = Release(tmp_path, monkeypatch)
    monkeypatch.undo()  # drop the test key: the real, shipped keys apply
    if sigverify.decode_keys():
        pytest.skip("real release keys are embedded")
    with pytest.raises(UpdateError, match="no release signing key"):
        release.updater.stage(release.info)
    assert NAME not in release.requested


def test_a_missing_signature_asset_is_named(tmp_path, monkeypatch):
    release = Release(tmp_path, monkeypatch)
    info = UpdateInfo("9.9.9", "u", tuple(a for a in release.info.assets if a.name != "SHA256SUMS.sig"))
    with pytest.raises(UpdateError, match=r"has no SHA256SUMS\.sig"):
        release.updater.stage(info)
