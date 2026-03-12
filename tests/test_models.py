"""Tests for the Episode data model."""

from datetime import datetime, timezone

import pytest

from lostfilm.models import Episode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_episode():
    return Episode(
        id="12345",
        title="Breaking Bad [S05E16]",
        link="http://www.lostfilm.tv/series/Breaking_Bad/season5/episode16/",
        pub_date=datetime(2013, 9, 29, 21, 0, 0, tzinfo=timezone.utc),
        qualities={"720p": "https://n.tracktor.site/rssdownloader.php?id=12345"}
    )


# ---------------------------------------------------------------------------
# Construction & attribute access
# ---------------------------------------------------------------------------


class TestEpisodeConstruction:
    def test_attributes_are_stored(self, sample_episode):
        assert sample_episode.id == "12345"
        assert sample_episode.title == "Breaking Bad [S05E16]"
        assert "lostfilm.tv" in sample_episode.link
        assert sample_episode.pub_date.year == 2013
        assert sample_episode.qualities["720p"] == "https://n.tracktor.site/rssdownloader.php?id=12345"

    def test_string_id_is_accepted(self):
        ep = Episode(
            id="hash-999", title="Test", link="http://example.com", pub_date=datetime.now(), qualities={}
        )
        assert ep.id == "hash-999"





# ---------------------------------------------------------------------------
# to_dict()
# ---------------------------------------------------------------------------


class TestToDict:
    def test_to_dict_has_required_keys(self, sample_episode):
        d = sample_episode.to_dict()
        assert set(d.keys()) == {"id", "title", "link", "pub_date", "qualities"}

    def test_to_dict_id_is_string(self, sample_episode):
        d = sample_episode.to_dict()
        assert isinstance(d["id"], str)

    def test_to_dict_pub_date_is_iso(self, sample_episode):
        d = sample_episode.to_dict()
        # Should parse back without error
        parsed = datetime.fromisoformat(d["pub_date"])
        assert parsed.year == 2013

    def test_to_dict_qualities_matches_property(self, sample_episode):
        d = sample_episode.to_dict()
        assert d["qualities"] == sample_episode.qualities

    def test_to_dict_title_preserved(self, sample_episode):
        d = sample_episode.to_dict()
        assert d["title"] == sample_episode.title
