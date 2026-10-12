from __future__ import annotations

import httpx
import pytest
import respx

from cfbtui.update import RELEASES_URL, UpdateInfo, check_for_update, is_newer, update_message

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
