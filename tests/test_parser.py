"""Tests for RSS feed parsing (parser.py)."""

import pytest

from lostfilm.exceptions import ParseError
from lostfilm.parser import _extract_numeric_id, parse_rss_feed


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_rss2(items_xml: str) -> str:
    """Wrap item XML fragments in a minimal RSS 2.0 envelope."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        "    <title>LostFilm.TV RSS</title>\n" + items_xml + "  </channel>\n"
        "</rss>\n"
    )


def make_atom(entries_xml: str) -> str:
    """Wrap entry XML fragments in a minimal Atom envelope."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "  <title>LostFilm.TV</title>\n" + entries_xml + "</feed>\n"
    )


RSS2_SINGLE_ITEM = make_rss2(
    "  <item>\n"
    "    <title>Breaking Bad [S05E16] [720p]</title>\n"
    "    <link>http://www.lostfilm.tv/eps/12345</link>\n"
    "    <guid>https://n.tracktor.site/rssdownloader.php?id=12345</guid>\n"
    "    <pubDate>Sun, 29 Sep 2013 21:00:00 +0000</pubDate>\n"
    "  </item>\n"
)

RSS2_TWO_ITEMS = make_rss2(
    "  <item>\n"
    "    <title>Show A [S01E01]</title>\n"
    "    <link>http://www.lostfilm.tv/eps/100</link>\n"
    "    <guid>https://n.tracktor.site/rssdownloader.php?id=100</guid>\n"
    "    <pubDate>Mon, 01 Jan 2024 10:00:00 +0000</pubDate>\n"
    "  </item>\n"
    "  <item>\n"
    "    <title>Show B [S02E03]</title>\n"
    "    <link>http://www.lostfilm.tv/eps/200</link>\n"
    "    <guid>https://n.tracktor.site/rssdownloader.php?id=200</guid>\n"
    "    <pubDate>Tue, 02 Jan 2024 10:00:00 +0000</pubDate>\n"
    "  </item>\n"
)

ATOM_SINGLE_ENTRY = make_atom(
    "  <entry>\n"
    "    <title>Severance [S01E01] [1080p]</title>\n"
    "    <id>https://n.tracktor.site/rssdownloader.php?id=99999</id>\n"
    '    <link href="http://www.lostfilm.tv/series/Severance/season1/episode1/"/>\n'
    "    <published>2022-02-18T00:00:00Z</published>\n"
    "  </entry>\n"
)


# ---------------------------------------------------------------------------
# _extract_numeric_id
# ---------------------------------------------------------------------------


class TestExtractNumericId:
    @pytest.mark.parametrize(
        "identifier,expected",
        [
            ("https://n.tracktor.site/rssdownloader.php?id=12345", "12345"),
            ("http://site.com/series/12345/", "12345"),
            ("67890", "67890"),
            ("id=0", "0"),
        ],
    )
    def test_known_patterns(self, identifier, expected):
        assert _extract_numeric_id(identifier) == expected

    def test_prefers_id_param_over_path(self):
        # URL has both id= param and /999/ path — id= wins because it's first pattern
        result = _extract_numeric_id("http://example.com/999/?id=111")
        assert result == "111"

    def test_returns_empty_string_for_non_numeric(self):
        assert _extract_numeric_id("no-numbers-here") == ""

    def test_returns_empty_string_for_empty_input(self):
        assert _extract_numeric_id("") == ""


# ---------------------------------------------------------------------------
# parse_rss_feed — RSS 2.0
# ---------------------------------------------------------------------------


class TestParseRss2Feed:
    def test_single_item_returns_one_episode(self):
        episodes = parse_rss_feed(RSS2_SINGLE_ITEM)
        assert len(episodes) == 1

    def test_episode_title(self):
        episodes = parse_rss_feed(RSS2_SINGLE_ITEM)
        assert episodes[0].title == "Breaking Bad [S05E16] [720p]"

    def test_episode_id_extracted_from_guid_url(self):
        episodes = parse_rss_feed(RSS2_SINGLE_ITEM)
        assert episodes[0].id == "12345"

    def test_episode_pub_date_parsed(self):
        episodes = parse_rss_feed(RSS2_SINGLE_ITEM)
        assert episodes[0].pub_date.year == 2013
        assert episodes[0].pub_date.month == 9

    def test_episode_download_url(self):
        episodes = parse_rss_feed(RSS2_SINGLE_ITEM)
        assert "id=12345" in episodes[0].download_url

    def test_two_items_returns_two_episodes(self):
        episodes = parse_rss_feed(RSS2_TWO_ITEMS)
        assert len(episodes) == 2

    def test_link_extracted(self):
        episodes = parse_rss_feed(RSS2_SINGLE_ITEM)
        assert "lostfilm.tv" in episodes[0].link

    def test_id_from_link_when_no_guid(self):
        xml = make_rss2(
            "  <item>\n"
            "    <title>No Guid Show [S01E01]</title>\n"
            "    <link>http://www.lostfilm.tv/eps/55555</link>\n"
            "    <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>\n"
            "  </item>\n"
        )
        episodes = parse_rss_feed(xml)
        assert len(episodes) == 1
        assert episodes[0].id == "55555"

    def test_invalid_pub_date_falls_back_to_now(self):
        xml = make_rss2(
            "  <item>\n"
            "    <title>Bad Date Show [S01E01]</title>\n"
            "    <guid>https://n.tracktor.site/rssdownloader.php?id=77777</guid>\n"
            "    <pubDate>not-a-date</pubDate>\n"
            "  </item>\n"
        )
        # Should not raise; falls back to datetime.now()
        episodes = parse_rss_feed(xml)
        assert len(episodes) == 1

    def test_item_without_numeric_id_is_skipped(self):
        xml = make_rss2(
            "  <item>\n"
            "    <title>No ID Show [S01E01]</title>\n"
            "    <guid>no-numeric-id-here</guid>\n"
            "    <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>\n"
            "  </item>\n"
            "  <item>\n"
            "    <title>Valid Show [S01E02]</title>\n"
            "    <guid>https://n.tracktor.site/rssdownloader.php?id=88888</guid>\n"
            "    <pubDate>Tue, 02 Jan 2024 00:00:00 +0000</pubDate>\n"
            "  </item>\n"
        )
        episodes = parse_rss_feed(xml)
        assert len(episodes) == 1
        assert episodes[0].id == "88888"


# ---------------------------------------------------------------------------
# parse_rss_feed — Atom format
# ---------------------------------------------------------------------------


class TestParseAtomFeed:
    def test_single_entry_returns_one_episode(self):
        episodes = parse_rss_feed(ATOM_SINGLE_ENTRY)
        assert len(episodes) == 1

    def test_atom_episode_title(self):
        episodes = parse_rss_feed(ATOM_SINGLE_ENTRY)
        assert "Severance" in episodes[0].title

    def test_atom_id_extracted(self):
        episodes = parse_rss_feed(ATOM_SINGLE_ENTRY)
        assert episodes[0].id == "99999"

    def test_atom_pub_date_parsed(self):
        episodes = parse_rss_feed(ATOM_SINGLE_ENTRY)
        assert episodes[0].pub_date.year == 2022


# ---------------------------------------------------------------------------
# parse_rss_feed — Error cases
# ---------------------------------------------------------------------------


class TestParseRssFeedErrors:
    def test_malformed_xml_raises_parse_error(self):
        with pytest.raises(ParseError, match="Failed to parse XML"):
            parse_rss_feed("<rss><unclosed>")

    def test_empty_channel_raises_parse_error(self):
        xml = make_rss2("")  # no <item> elements
        with pytest.raises(ParseError):
            parse_rss_feed(xml)

    def test_all_items_invalid_raises_parse_error(self):
        xml = make_rss2(
            "  <item>\n"
            "    <title>Only Letters As ID</title>\n"
            "    <guid>no-numbers</guid>\n"
            "  </item>\n"
        )
        with pytest.raises(ParseError, match="No valid episodes"):
            parse_rss_feed(xml)

    def test_completely_empty_string_raises_parse_error(self):
        with pytest.raises(ParseError):
            parse_rss_feed("")
