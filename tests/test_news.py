"""The news feed: parsing, tags, the story renderer, the poller (present, away, backoff), reading, and the screens."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import respx
from textual.widgets import Markdown, OptionList, Static

from cfbtui.app import CfbApp
from cfbtui.espn.client import BASE_URL, EspnClient, EspnError, EspnHttpError, EspnNetworkError, EspnSchemaError
from cfbtui.espn.models import NewsItem, NewsTeam
from cfbtui.espn.parse import parse_news, parse_story
from cfbtui.news import NEWS_BACKOFF_MAX, NEWS_INTERVAL, STORY_CACHE, NewsFeed
from cfbtui.poll import FreshnessState, PollScheduler
from cfbtui.ui.filters import conference_name
from cfbtui.ui.glyphs import ASCII
from cfbtui.ui.screens.news import NewsScreen, StoryScreen, age_label, chips, health_line, team_conferences
from cfbtui.ui.story import MAX_CHARS, markdown_parser, render_story
from cfbtui.ui.widgets.status_bar import StatusBar
from tests.fakes import FIXTURES, FakeClient, FakeClock, load_board
from tests.test_app_smoke import FAST, SIZE, wait_for
from tests.test_screens import screen_text

NEWS = json.loads((FIXTURES / "news.json").read_text(encoding="utf-8"))
STORY = json.loads((FIXTURES / "news_story.json").read_text(encoding="utf-8"))
ITEMS = parse_news(NEWS)
BY_ID = {i.id: i for i in ITEMS}
NEWS_URL = "https://content.core.api.espn.com/v1/sports/news/9002"
AWAY = 10_000.0


class Presence:
    def __init__(self, away: bool = False) -> None:
        self.away = away

    def __call__(self) -> float:
        return AWAY if self.away else 0.0


def make_feed(client: FakeClient, presence: Presence | None = None, **kwargs) -> tuple[NewsFeed, FakeClock, Presence]:
    clock = FakeClock()
    presence = presence or Presence()
    scheduler = PollScheduler(client, idle_for=presence)
    return NewsFeed(client, scheduler, clock=clock, **kwargs), clock, presence


def item(item_id: str, *teams: str, published: datetime | None = None) -> NewsItem:
    return NewsItem(
        id=item_id, kind="Story", headline=f"Headline {item_id}", description="", web_url=None,
        published=published or datetime(2026, 10, 26, tzinfo=UTC), teams=tuple(NewsTeam(t, t) for t in teams),
    )


# --- parsing -------------------------------------------------------------------------


def test_parse_news_skips_articles_without_an_id_or_headline_and_junk():
    assert [i.id for i in ITEMS] == ["9001", "9002", "9003", "9004", "9006", "9008"]


def test_each_team_is_listed_once_though_espn_lists_it_twice():
    assert len(ITEMS[0].teams) == 2 and len({t.id for t in ITEMS[0].teams}) == 2
    assert all(t.name for t in ITEMS[0].teams)
    assert len(BY_ID["9003"].teams) == 7 and len(BY_ID["9008"].teams) == 6
    assert BY_ID["9006"].teams == ()


def test_kind_premium_and_links_come_through():
    story, premium = BY_ID["9002"], BY_ID["9004"]
    assert story.kind == "HeadlineNews" and not story.premium and story.readable
    assert story.story_url == NEWS_URL and story.web_url.startswith("https://www.espn.com/")
    assert premium.premium and not premium.readable
    assert story.published == datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def test_parse_news_tolerates_garbage_at_every_level():
    assert parse_news({}) == () and parse_news(None) == () and parse_news({"articles": "x"}) == ()
    one = parse_news({"articles": [{"id": 1, "headline": "H", "categories": "nope", "links": [], "published": 5}]})
    assert one[0].teams == () and one[0].web_url is None and one[0].story_url is None


def test_parse_story_takes_the_first_headlines_body():
    assert parse_story(STORY).startswith("<p><photo1></p>")
    assert parse_story({}) == "" and parse_story({"headlines": []}) == "" and parse_story({"headlines": [{}]}) == ""


# --- client --------------------------------------------------------------------------


@pytest.fixture
def mock():
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


async def test_news_asks_for_thirty_and_parses(mock):
    route = mock.get("/news").respond(200, json=NEWS)
    async with EspnClient() as client:
        items = await client.news()
    assert [i.id for i in items][:2] == ["9001", "9002"]
    assert route.calls.last.request.url.params["limit"] == "30"


async def test_a_news_payload_without_an_articles_list_is_a_schema_error(mock):
    mock.get("/news").respond(200, json={"header": "x"})
    async with EspnClient() as client:
        with pytest.raises(EspnSchemaError):
            await client.news()


async def test_an_empty_articles_list_is_fine(mock):
    mock.get("/news").respond(200, json={"articles": []})
    async with EspnClient() as client:
        assert await client.news() == ()


async def test_story_fetches_the_api_link_with_the_apps_user_agent():
    with respx.mock(assert_all_called=False) as router:
        route = router.get(NEWS_URL).respond(200, json=STORY)
        async with EspnClient() as client:
            html = await client.story(NEWS_URL)
    assert "Final paragraph." in html
    assert route.calls.last.request.headers["user-agent"].startswith("cfbtui/")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1/sports/news/1",
        "http://content.core.api.espn.com/v1/sports/news/1",
        "https://content.core.api.espn.com/other/1",
        "https://content.core.api.espn.com/v1/sports/news/",
        "https://content.core.api.espn.com/v1/sports/news/../../x",
        "https://content.core.api.espn.com.evil.example/v1/sports/news/1",
        "",
    ],
)
async def test_story_refuses_any_url_that_is_not_an_espn_story_link(url):
    async with EspnClient() as client:
        with pytest.raises(EspnError, match="Not a story link"):
            await client.story_raw(url)


async def test_story_treats_a_4xx_as_final_and_retries_a_5xx():
    slept: list[float] = []

    async def sleep(delay: float) -> None:
        slept.append(delay)

    with respx.mock(assert_all_called=False) as router:
        route = router.get(NEWS_URL).mock(side_effect=[httpx.Response(404), httpx.Response(200, json=STORY)])
        async with EspnClient(sleep=sleep) as client:
            with pytest.raises(EspnHttpError):
                await client.story(NEWS_URL)
            assert route.call_count == 1 and slept == []
        router.get(NEWS_URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, json=STORY)])
        async with EspnClient(sleep=sleep) as client:
            assert "Final paragraph." in await client.story(NEWS_URL)
        assert len(slept) == 1


# --- tags ----------------------------------------------------------------------------


def board_of(**team_conferences_: str | None):
    team = lambda i: SimpleNamespace(id=i, conference_id=team_conferences_[i])  # noqa: E731
    ids = list(team_conferences_)
    games = [SimpleNamespace(away=SimpleNamespace(team=team(a)), home=SimpleNamespace(team=team(b)))
             for a, b in zip(ids[::2], ids[1::2], strict=False)]
    return team_conferences(games)


def test_conference_map_comes_from_the_board_and_skips_teams_without_one():
    assert board_of(a="8", b="4", c=None, d="8") == {"a": "8", "b": "4", "d": "8"}


def test_chips_name_teams_and_their_distinct_conferences_in_order():
    conferences = {"1": "8", "2": "8", "3": "4"}
    teams, confs = chips(item("x", "1", "2", "3"), conferences)
    assert teams == ["1", "2", "3"] and confs == [conference_name("8"), conference_name("4")] and confs[0] != confs[1]


def test_a_bye_team_has_a_team_chip_and_no_conference_chip():
    teams, confs = chips(item("x", "1", "9"), {"1": "8"})
    assert teams == ["1", "9"] and confs == [conference_name("8")]
    assert chips(item("x", "9"), {}) == (["9"], [])


def test_an_unknown_conference_id_uses_the_conference_fallback_name():
    assert chips(item("x", "1"), {"1": "9999"})[1] == ["Conference 9999"]


def test_more_than_six_teams_is_a_roundup_with_no_chips_and_six_still_gets_them():
    ids = [str(n) for n in range(7)]
    conferences = dict.fromkeys(ids, "8")
    assert chips(item("x", *ids), conferences) == ([], [])
    assert chips(item("x", *ids[:6]), conferences)[0] == ids[:6]
    assert chips(BY_ID["9003"], {t.id: "8" for t in BY_ID["9003"].teams}) == ([], [])


def test_age_label():
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    assert age_label(now, now) == "1m"
    assert age_label(datetime(2026, 10, 26, 11, 15, tzinfo=UTC), now) == "45m"
    assert age_label(datetime(2026, 10, 26, 9, 0, tzinfo=UTC), now) == "3h"
    assert age_label(datetime(2026, 10, 24, 12, 0, tzinfo=UTC), now) == "2d"


# --- story rendering -----------------------------------------------------------------


def test_story_html_becomes_markdown_with_paragraphs_breaks_rule_and_emphasis():
    assert render_story(parse_story(STORY)).markdown == (
        "Alpha opened the **sample** game with a *long* drive, per Alpha sources.\\\n"
        "Second line after a break.\n\n---\n\nBeta \\& Alpha meet again.\n\nFinal paragraph."
    )


def test_headings_lists_and_quotes_keep_their_shape():
    html = "<h2>Notes</h2><ul><li>one</li><li>two</li></ul><blockquote><p>said <b>so</b></p></blockquote><p>end</p>"
    assert render_story(html).markdown == "## Notes\n\n- one\n- two\n\n> said **so**\n\nend"


def test_text_that_markdown_would_read_as_syntax_is_escaped_and_links_keep_only_their_text():
    html = "<p># not a heading *x* _y_ [a](http://e.x) &lt;b&gt;h&lt;/b&gt; `c`</p><p>- no<br>1. no</p><p><a href='http://e.x'>link</a></p>"
    md = render_story(html).markdown
    out = markdown_parser().render(md)
    for tag in ("<h1", "<em>", "<strong>", "<ul>", "<ol>", "<a ", "<b>", "<code>"):
        assert tag not in out
    assert md.endswith("link") and "http://e.x'" not in md


def test_pathological_input_is_capped():
    assert len(render_story("<p>" + "word *" * MAX_CHARS + "</p>").markdown) <= MAX_CHARS
    assert render_story("<b>" * 50_000 + "x").markdown.count("x") == 1


def test_images_and_media_placeholders_leave_nothing_and_links_keep_their_text():
    plain = render_story(parse_story(STORY)).plain
    for junk in ("photo1", "video1", "alsosee", "img", "http", "<", ">"):
        assert junk not in plain
    assert "per Alpha sources" in plain


def test_scripts_are_dropped_and_odd_input_never_raises():
    assert render_story("<script>alert(1)</script><p>ok</p>").plain == "ok"
    assert render_story("").plain == "" and render_story("<p> </p><br>").plain == ""
    assert render_story("<p>unclosed <strong>bold").plain == "unclosed **bold**"
    assert render_story("</p></strong>text").plain == "text"


# --- feed state ----------------------------------------------------------------------


async def test_a_poll_lists_newest_first_and_every_story_is_unread_until_opened():
    client = FakeClient()
    client.news_items = ITEMS
    feed, _, _ = make_feed(client)
    await feed.poll_once()
    assert [i.id for i in feed.items][:3] == ["9001", "9008", "9002"]
    assert feed.unread_count == len(ITEMS)
    feed.mark_read(BY_ID["9001"])
    feed.mark_read(BY_ID["9001"])
    assert feed.unread_count == len(ITEMS) - 1 and not feed.is_unread(BY_ID["9001"])
    await feed.poll_once()  # a refresh does not make it unread again
    assert feed.unread_count == len(ITEMS) - 1


async def test_failures_keep_the_last_list_and_the_wait_doubles_to_the_cap():
    client = FakeClient()
    client.news_items = ITEMS
    feed, clock, _ = make_feed(client)
    assert feed.freshness().state is FreshnessState.LOADING
    await feed.poll_once()
    assert feed.freshness().state is FreshnessState.FRESH and feed.next_delay() == NEWS_INTERVAL
    client.news_items = EspnNetworkError("down")
    delays = []
    for _ in range(4):
        clock.advance(30)
        await feed.poll_once()
        delays.append(feed.next_delay())
    assert delays == [1200.0, 1800.0, 1800.0, 1800.0] and delays[-1] == NEWS_BACKOFF_MAX
    assert len(feed.items) == len(ITEMS)  # the stale list stays
    f = feed.freshness()
    assert f.state is FreshnessState.ERROR and f.failures == 4 and "EspnNetworkError" in f.error
    assert "ERROR showing news 2m00s old" in health_line(f, ASCII)
    client.news_items = ITEMS
    await feed.poll_once()
    assert feed.freshness().state is FreshnessState.FRESH and feed.next_delay() == NEWS_INTERVAL


async def test_the_list_goes_stale_after_two_and_a_half_intervals():
    client = FakeClient()
    client.news_items = ITEMS
    feed, clock, _ = make_feed(client)
    await feed.poll_once()
    clock.advance(NEWS_INTERVAL * 2.5)
    assert feed.freshness().state is FreshnessState.FRESH
    clock.advance(1)
    assert feed.freshness().state is FreshnessState.STALE
    assert health_line(feed.freshness(), ASCII).startswith("~ STALE 25m01s old")


async def test_an_error_before_any_news_says_no_data_yet():
    client = FakeClient()
    client.news_items = EspnNetworkError("down")
    feed, _, _ = make_feed(client)
    await feed.poll_once()
    assert "ERROR no data yet" in health_line(feed.freshness(), ASCII)


# --- presence ------------------------------------------------------------------------


async def settle(seconds: float = 0.15) -> None:
    await asyncio.sleep(seconds)


async def test_the_poller_polls_while_present_and_sends_nothing_while_away():
    client = FakeClient()
    client.news_items = ITEMS
    away = Presence(away=True)
    feed, _, _ = make_feed(client, away, interval=0.03)
    task = asyncio.create_task(feed.run())
    await settle()
    assert client.news_calls == 0  # started away: parked
    away.away = False
    feed.refresh()
    await settle()
    first = client.news_calls
    assert first >= 2  # one at once on return, then on its interval
    away.away = True
    feed.refresh()
    await settle()  # the timer may fire once more, but it sees nobody and parks
    parked = client.news_calls
    await settle(0.3)
    assert client.news_calls == parked
    feed.stop()
    await asyncio.wait_for(task, 1)


async def test_coming_back_polls_once_at_once_without_waiting_out_the_interval():
    client = FakeClient()
    client.news_items = ITEMS
    presence = Presence()
    feed, _, _ = make_feed(client, presence)  # a 10 minute interval
    task = asyncio.create_task(feed.run())
    await settle()
    assert client.news_calls == 1
    presence.away = True
    feed.refresh()
    await settle()
    presence.away = False
    feed.refresh()
    await settle()
    assert client.news_calls == 2
    feed.stop()
    await asyncio.wait_for(task, 1)


async def test_refresh_while_away_sends_nothing():
    client = FakeClient()
    feed, _, _ = make_feed(client, Presence(away=True), interval=0.03)
    task = asyncio.create_task(feed.run())
    await settle()
    feed.refresh()
    await settle()
    assert client.news_calls == 0
    feed.stop()
    await asyncio.wait_for(task, 1)


# --- reading -------------------------------------------------------------------------


async def test_the_poller_never_requests_a_story_body():
    client = FakeClient()
    client.news_items = ITEMS
    feed, _, _ = make_feed(client, interval=0.02)
    task = asyncio.create_task(feed.run())
    await settle(0.2)
    assert client.news_calls >= 2 and client.story_calls == []
    feed.stop()
    await asyncio.wait_for(task, 1)


async def test_a_story_is_requested_once_per_open_then_served_from_memory():
    client = FakeClient()
    client.stories[NEWS_URL] = "<p>Text</p>"
    feed, _, _ = make_feed(client)
    story = BY_ID["9002"]
    assert await feed.read(story) == "<p>Text</p>" and await feed.read(story) == "<p>Text</p>"
    assert client.story_calls == [NEWS_URL]


async def test_the_story_cache_keeps_only_the_last_twenty():
    client = FakeClient()
    feed, _, _ = make_feed(client)
    stories = [
        NewsItem(str(n), "Story", f"H{n}", "", datetime(2026, 10, 26, tzinfo=UTC), story_url=f"https://x/{n}")
        for n in range(STORY_CACHE + 1)
    ]
    for s in stories:
        await feed.read(s)
    assert len(client.story_calls) == STORY_CACHE + 1
    await feed.read(stories[-1])  # recent: cached
    assert len(client.story_calls) == STORY_CACHE + 1
    await feed.read(stories[0])  # the oldest was dropped: fetched again
    assert len(client.story_calls) == STORY_CACHE + 2


async def test_a_failed_story_fetch_is_not_cached():
    client = FakeClient()
    feed, _, _ = make_feed(client)

    async def boom(url: str) -> str:
        raise EspnNetworkError("down")

    client.story = boom
    with pytest.raises(EspnNetworkError):
        await feed.read(BY_ID["9002"])
    assert not feed._stories


# --- screens -------------------------------------------------------------------------


def news_client(**stories: str) -> FakeClient:
    client = FakeClient(load_board("pairs/final_after.json"))
    client.news_items = ITEMS
    client.stories.update(stories or {NEWS_URL: parse_story(STORY)})
    return client


async def open_news(pilot, app) -> NewsScreen:
    await wait_for(pilot, lambda: app.news.items)
    await pilot.press("N")
    await wait_for(pilot, lambda: isinstance(app.screen, NewsScreen))
    return app.screen


async def test_n_opens_the_list_newest_first_with_unread_markers_and_chips():
    app = CfbApp(client=news_client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        lst = screen.query_one(OptionList)
        assert lst.option_count == len(ITEMS)
        prompts = [str(lst.get_option_at_index(n).prompt) for n in range(lst.option_count)]
        assert prompts[0].startswith("NEW ") and not any("video" in p.lower() for p in prompts)
        assert any("Sample preview: Alpha at Beta" in p and "[UCF]" in p for p in prompts)
        roundup = next(p for p in prompts if "many teams" in p)
        assert "[" not in roundup
        assert f"{len(ITEMS)} unread" in screen_text(app)


async def test_enter_reads_the_story_in_the_app_with_attribution_and_marks_it_read():
    client = news_client()
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        assert client.story_calls == []  # opening the list fetches no body
        lst = screen.query_one(OptionList)
        lst.highlighted = next(n for n in range(lst.option_count) if lst.get_option_at_index(n).id == "9002")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, StoryScreen) and app.screen.loaded)
        text = screen_text(app)
        assert "Sample story about one team" in text and "Final paragraph." in text
        assert "ESPN. Press O to open the original" in text and "https://www.espn.com/" in text
        assert client.story_calls == [NEWS_URL]
        assert app.news.unread_count == len(ITEMS) - 1
        await pilot.press("escape")
        await wait_for(pilot, lambda: isinstance(app.screen, NewsScreen))
        assert app.screen.query_one(OptionList).get_option_at_index(lst.highlighted).prompt.plain.startswith("    ")


async def test_a_premium_story_shows_the_description_and_fetch_nothing():
    client = news_client()
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        lst = screen.query_one(OptionList)
        for story_id, description, note in (("9004", "Premium sample description.", "premium story"),):
            lst.highlighted = next(n for n in range(lst.option_count) if lst.get_option_at_index(n).id == story_id)
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, StoryScreen) and app.screen.loaded)
            text = screen_text(app)
            assert description in text and note in text and "Press O to open the original" in text
            await pilot.press("escape")
            await wait_for(pilot, lambda: isinstance(app.screen, NewsScreen))
        assert client.story_calls == []


async def test_a_link_in_a_story_does_nothing_and_the_story_is_fetched_once():
    opened: list[str] = []
    html = "<p>See www.espn.com/x and https://evil.example/ and [m](https://evil.example/)</p>"
    client = news_client(**{NEWS_URL: html})
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        screen.opener = opened.append
        lst = screen.query_one(OptionList)
        lst.highlighted = next(n for n in range(lst.option_count) if lst.get_option_at_index(n).id == "9002")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, StoryScreen) and app.screen.loaded)
        md = app.screen.query_one(Markdown)
        assert md._open_links is False
        assert "https://evil.example/" in screen_text(app) and "[m](https://evil.example/)" in screen_text(app)
        await pilot.click("MarkdownParagraph", offset=(5, 0))
        assert opened == [] and isinstance(app.screen, StoryScreen)
        assert client.story_calls == [NEWS_URL]


async def test_a_failed_story_load_says_so_and_keeps_the_open_action():
    client = news_client()

    async def boom(url: str) -> str:
        raise EspnNetworkError("no route")

    client.story = boom
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        lst = screen.query_one(OptionList)
        lst.highlighted = next(n for n in range(lst.option_count) if lst.get_option_at_index(n).id == "9002")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, StoryScreen) and app.screen.loaded)
        text = screen_text(app)
        assert "Could not load the story (no route)" in text and "A sample description of a one-team story." in text
        assert "Press O to open the original" in text


async def test_o_opens_the_original_in_the_browser_and_marks_it_read():
    opened: list[str] = []
    app = CfbApp(client=news_client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        screen.opener = opened.append
        lst = screen.query_one(OptionList)
        lst.highlighted = next(n for n in range(lst.option_count) if lst.get_option_at_index(n).id == "9001")
        await pilot.press("o")
        assert opened == [BY_ID["9001"].web_url] and not app.news.is_unread(BY_ID["9001"])


async def test_o_will_not_open_a_link_that_is_not_on_espn():
    opened: list[str] = []
    bad = NewsItem("1", "Story", "H", "", datetime(2026, 10, 26, tzinfo=UTC), web_url="https://evil.example/x")
    client = FakeClient(load_board("pairs/final_after.json"))
    client.news_items = (bad,)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        screen.opener = opened.append
        await pilot.press("o")
        assert opened == [] and any("No link" in n.message for n in app._notifications)


async def test_the_status_bar_counts_unread_stories_and_n_is_in_help():
    app = CfbApp(client=news_client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await wait_for(pilot, lambda: app.news.items)
        await wait_for(pilot, lambda: f"{len(ITEMS)} unread news" in app.query_one(StatusBar).text)
        await pilot.press("question_mark")
        await wait_for(pilot, lambda: "News" in screen_text(app))
        assert any(line.strip().startswith("N ") and "News" in line for line in screen_text(app).splitlines())


async def test_the_news_screen_keeps_the_last_list_and_says_so_when_the_feed_fails():
    client = news_client()
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        client.news_items = EspnNetworkError("down")
        app.news.refresh()
        await wait_for(pilot, lambda: app.news.freshness().state is FreshnessState.ERROR)
        await pilot.pause(0.1)
        assert screen.query_one(OptionList).option_count == len(ITEMS)
        assert "ERROR showing news" in str(screen.query_one("#news-health", Static).content)


# --- review fixes: hostile or odd payloads, sinks ------------------------------------


def test_video_clips_never_reach_the_list_or_the_unread_count():
    clip = {"id": 1, "headline": "Clip", "type": "Media"}
    assert parse_news({"articles": [clip]}) == ()
    assert "9005" not in BY_ID and all(i.kind.lower() != "media" for i in ITEMS)
    assert any(a.get("type") == "Media" for a in NEWS["articles"])  # the fixture still carries one


def test_a_repeated_id_keeps_the_first_article():
    first = {"id": 1, "headline": "First", "type": "Story"}
    again = {"id": "1", "headline": "Again", "type": "Media"}
    other = {"id": 2, "headline": "Other"}
    assert [i.headline for i in parse_news({"articles": [first, other, again]})] == ["First", "Other"]


def test_control_characters_are_stripped_from_payload_text():
    raw = {"id": 1, "headline": "Hi\x1b]52;c;AAAA\x1b\\ there\x9b", "description": "a\x07b\nc", "categories": []}
    (parsed,) = parse_news({"articles": [raw]})
    assert "\x1b" not in parsed.headline and "\x9b" not in parsed.headline and "\x07" not in parsed.description
    assert "\n" in parsed.description
    assert "\x1b" not in render_story("<p>x\x1b]0;title\x07y</p>").plain


@pytest.mark.parametrize(
    "url",
    [r"https://evil.example\@www.espn.com/x", "https://user@www.espn.com/x", "https://www.espn.com/a b",
     "https://evil.example/", "javascript:alert(1)", "https://www.espn.com.evil.example/", "", None],
)
def test_links_a_browser_could_read_differently_are_refused(url):
    from cfbtui.ui.screens.news import is_espn_link

    assert not is_espn_link(url)


def test_ordinary_espn_links_pass():
    from cfbtui.ui.screens.news import is_espn_link

    assert is_espn_link("https://www.espn.com/college-football/story/_/id/1/x")


async def test_a_headline_that_looks_like_markup_is_shown_as_text_and_a_repeat_id_does_not_crash_the_list():
    evil = NewsItem("1", "Story", "Read [/] [@click=app.quit]more[/]", "d", datetime(2026, 10, 26, tzinfo=UTC),
                    web_url="https://www.espn.com/x", story_url=NEWS_URL)
    client = FakeClient(load_board("pairs/final_after.json"))
    client.news_items = (evil,)
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, StoryScreen) and app.screen.loaded)
        assert "Read [/] [@click=app.quit]more[/]" in screen_text(app)
        assert screen is not app.screen


async def test_an_opener_that_finds_no_browser_says_so_and_shows_the_link():
    app = CfbApp(client=news_client(), intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_news(pilot, app)
        screen.opener = lambda url: False
        await pilot.press("o")
        assert any("No browser" in n.message and "https://www.espn.com/" in n.message for n in app._notifications)


async def test_the_list_repaints_when_you_come_back_from_a_story():
    client = news_client()
    app = CfbApp(client=client, intervals=FAST, glyph_set="ascii")
    async with app.run_test(size=SIZE) as pilot:
        await open_news(pilot, app)
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, StoryScreen))
        client.news_items = ITEMS[:2]
        app.news.refresh()
        await wait_for(pilot, lambda: len(app.news.items) == 2)
        await pilot.press("escape")
        await wait_for(pilot, lambda: isinstance(app.screen, NewsScreen))
        assert app.screen.query_one(OptionList).option_count == 2


async def test_a_failing_change_callback_does_not_kill_the_poller():
    client = FakeClient()
    client.news_items = ITEMS

    def boom() -> None:
        raise RuntimeError("ui fault")

    feed, _, _ = make_feed(client, on_change=boom)
    await feed.poll_once()
    assert len(feed.items) == len(ITEMS)
