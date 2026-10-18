from __future__ import annotations

import httpx
import pytest
import respx

from cfbtui.update import (
    RELEASES_URL,
    Asset,
    UpdateInfo,
    asset_name,
    check_for_update,
    install_kind,
    is_newer,
    pip_message,
    update_message,
)

URL = "https://github.com/WPTK/cfbtui/releases/tag/v1.2.0"


def release(**over):
    body = {"tag_name": "v1.2.0", "html_url": URL, "draft": False, "prerelease": False}
    body.update(over)
    return body


@pytest.fixture
def mock():
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.mark.parametrize(
    "candidate, current, expected",
    [
        ("1.2.0", "1.1.0", True),
        ("v1.2.0", "1.1.0", True),
        ("1.2.0", "v1.2.0", False),
        ("1.1.0", "1.2.0", False),
        ("0.10.0", "0.9.0", True),
        ("junk", "1.0.0", False),
        ("1.0.0", "junk", False),
        ("1.0", "0.1.0", False),
        ("", "", False),
    ],
)
def test_is_newer(candidate, current, expected):
    assert is_newer(candidate, current) is expected


async def test_newer_release_is_reported(mock):
    route = mock.get(RELEASES_URL).respond(200, json=release())
    info = await check_for_update("0.5.0")
    assert info == UpdateInfo("1.2.0", URL)
    sent = route.calls.last.request.headers
    assert sent["accept"] == "application/vnd.github+json"
    assert sent["user-agent"].startswith("cfbtui/")


async def test_same_version_is_none(mock):
    mock.get(RELEASES_URL).respond(200, json=release())
    assert await check_for_update("1.2.0") is None


async def test_older_release_is_none(mock):
    mock.get(RELEASES_URL).respond(200, json=release())
    assert await check_for_update("2.0.0") is None


async def test_draft_is_ignored(mock):
    mock.get(RELEASES_URL).respond(200, json=release(draft=True))
    assert await check_for_update("0.1.0") is None


async def test_prerelease_is_ignored(mock):
    mock.get(RELEASES_URL).respond(200, json=release(prerelease=True))
    assert await check_for_update("0.1.0") is None


@pytest.mark.parametrize("status", [404, 500])
async def test_http_errors_are_none(mock, status):
    mock.get(RELEASES_URL).respond(status)
    assert await check_for_update("0.1.0") is None


async def test_transport_error_is_none(mock):
    mock.get(RELEASES_URL).mock(side_effect=httpx.ConnectError("down"))
    assert await check_for_update("0.1.0") is None


async def test_invalid_json_is_none(mock):
    mock.get(RELEASES_URL).respond(200, content=b"not json")
    assert await check_for_update("0.1.0") is None


@pytest.mark.parametrize("body", [[], "x", {}, {"tag_name": 5, "html_url": URL}, {"tag_name": "v9.0.0"}])
async def test_odd_shapes_are_none(mock, body):
    mock.get(RELEASES_URL).respond(200, json=body)
    assert await check_for_update("0.1.0") is None


async def test_passed_client_is_left_open(mock):
    mock.get(RELEASES_URL).respond(200, json=release())
    async with httpx.AsyncClient() as client:
        assert await check_for_update("0.1.0", client=client) is not None
        assert not client.is_closed


def test_update_message():
    assert update_message(UpdateInfo("1.2.0", URL)) == f"cfbtui 1.2.0 is available. Get it at {URL}"


@pytest.mark.parametrize(
    "system, machine, expected",
    [
        ("Windows", "AMD64", "cfbtui-windows-x86_64.exe"),
        ("Linux", "x86_64", "cfbtui-linux-x86_64"),
        ("Linux", "aarch64", "cfbtui-linux-arm64"),
        ("Darwin", "arm64", "cfbtui-macos-arm64"),
        ("Darwin", "x86_64", "cfbtui-macos-x86_64"),
        ("Windows", "ARM64", "cfbtui-windows-arm64.exe"),
        ("FreeBSD", "amd64", None),
        ("Linux", "riscv64", None),
        ("Linux", "", None),
    ],
)
def test_asset_name(system, machine, expected):
    assert asset_name(system, machine) == expected


def test_asset_name_defaults_to_this_machine():
    assert asset_name() is None or asset_name().startswith("cfbtui-")


@pytest.mark.parametrize(
    "frozen, prefix, expected",
    [
        (True, "/anything", "binary"),
        (False, "/home/a/.local/pipx/venvs/cfbtui", "pipx"),
        (False, r"C:\Users\a\pipx\venvs\cfbtui", "pipx"),
        (False, "/home/a/.local/share/uv/tools/cfbtui", "uv"),
        (False, r"C:\Users\a\AppData\Roaming\uv\tools\cfbtui", "uv"),
        (False, "/usr", "pip"),
    ],
)
def test_install_kind(frozen, prefix, expected):
    assert install_kind(frozen=frozen, prefix=prefix) == expected


def test_install_kind_reads_sys_frozen(monkeypatch):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", "/tmp/x", raising=False)
    assert install_kind() == "binary"
    monkeypatch.delattr("sys._MEIPASS")
    assert install_kind(prefix="/usr") == "pip"


@pytest.mark.parametrize(
    "kind, command",
    [
        ("pipx", "pipx upgrade cfbtui"),
        ("uv", "uv tool upgrade cfbtui"),
        ("pip", "python -m pip install -U cfbtui"),
        ("binary", "python -m pip install -U cfbtui"),
    ],
)
def test_pip_message(kind, command):
    assert command in pip_message(kind)


async def test_assets_are_parsed(mock):
    assets = [
        {"name": "cfbtui-linux-x86_64", "browser_download_url": "https://x/a", "size": 5},
        {"name": "bad", "browser_download_url": "https://x/b", "size": "5"},
        "junk",
    ]
    mock.get(RELEASES_URL).mock(return_value=httpx.Response(200, json=release(assets=assets)))
    info = await check_for_update("1.0.0")
    assert info.assets == (Asset("cfbtui-linux-x86_64", "https://x/a", 5),)
    assert update_message(info).endswith(URL)


@pytest.mark.parametrize("over", [{}, {"assets": None}, {"assets": "x"}])
async def test_missing_assets_still_updates(mock, over):
    mock.get(RELEASES_URL).mock(return_value=httpx.Response(200, json=release(**over)))
    info = await check_for_update("1.0.0")
    assert info == UpdateInfo("1.2.0", URL) and info.assets == ()
