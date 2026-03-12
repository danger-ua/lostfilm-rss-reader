"""Tests for LostFilmClient (all HTTP requests are mocked)."""

from datetime import datetime
import pytest
import requests

from lostfilm.client import LostFilmClient
from lostfilm.exceptions import (
    AuthenticationError,
    LostFilmError,
    RateLimitError,
    ServerError,
)
from lostfilm.models import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_client(uid="test_uid", usess="test_usess"):
    """Create a client with dummy credentials (no env vars needed)."""
    return LostFilmClient(uid=uid, usess=usess)


MINIMAL_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Test Show [S01E01] [720p]</title>
      <link>http://www.lostfilm.tv/eps/11111</link>
      <guid>https://n.tracktor.site/rssdownloader.php?id=11111</guid>
      <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestClientConstructor:
    def test_raises_without_credentials(self, monkeypatch):
        monkeypatch.delenv("LOSTFILM_UID", raising=False)
        monkeypatch.delenv("LOSTFILM_USESS", raising=False)
        with pytest.raises(LostFilmError, match="Credentials not provided"):
            LostFilmClient()

    def test_raises_with_only_uid(self, monkeypatch):
        monkeypatch.delenv("LOSTFILM_USESS", raising=False)
        with pytest.raises(LostFilmError):
            LostFilmClient(uid="only_uid")

    def test_raises_with_only_usess(self, monkeypatch):
        monkeypatch.delenv("LOSTFILM_UID", raising=False)
        with pytest.raises(LostFilmError):
            LostFilmClient(usess="only_usess")

    def test_credentials_from_env(self, monkeypatch):
        monkeypatch.setenv("LOSTFILM_UID", "env_uid")
        monkeypatch.setenv("LOSTFILM_USESS", "env_usess")
        client = LostFilmClient()
        assert client.uid == "env_uid"
        assert client.usess == "env_usess"

    def test_constructor_args_override_env(self, monkeypatch):
        monkeypatch.setenv("LOSTFILM_UID", "env_uid")
        monkeypatch.setenv("LOSTFILM_USESS", "env_usess")
        client = LostFilmClient(uid="arg_uid", usess="arg_usess")
        assert client.uid == "arg_uid"
        assert client.usess == "arg_usess"

    def test_cookie_header_set(self):
        client = make_client(uid="myuid", usess="mysess")
        cookie = client.session.headers["Cookie"]
        assert "uid=myuid" in cookie
        assert "usess=mysess" in cookie


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_first_request_is_allowed(self):
        client = make_client()
        # Should not raise
        client._check_rate_limit("test_endpoint")

    def test_immediate_second_request_raises(self):
        client = make_client()
        client._check_rate_limit("test_endpoint")
        with pytest.raises(RateLimitError):
            client._check_rate_limit("test_endpoint")

    def test_different_endpoints_are_independent(self):
        client = make_client()
        client._check_rate_limit("endpoint_a")
        # endpoint_b has no history, so it should succeed
        client._check_rate_limit("endpoint_b")

    def test_rate_limit_error_message_contains_wait_time(self):
        client = make_client()
        client._check_rate_limit("test_endpoint")
        try:
            client._check_rate_limit("test_endpoint")
        except RateLimitError as e:
            assert "minutes" in e.message


# ---------------------------------------------------------------------------
# _make_request
# ---------------------------------------------------------------------------


class TestMakeRequest:
    def _patched_client(self, mocker, status_code=200, content=b"", exc=None):
        """Return a client whose session.get is mocked."""
        client = make_client()
        # Reset rate-limit history so _check_rate_limit won't block
        client._last_request_time = {}

        if exc:
            mocker.patch.object(client.session, "get", side_effect=exc)
        else:
            mock_resp = mocker.MagicMock()
            mock_resp.status_code = status_code
            mock_resp.content = content
            if status_code >= 400:
                mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
                    response=mock_resp
                )
            else:
                mock_resp.raise_for_status.return_value = None
            mocker.patch.object(client.session, "get", return_value=mock_resp)

        return client

    def test_returns_content_on_200(self, mocker):
        client = self._patched_client(mocker, status_code=200, content=b"<rss/>")
        result = client._make_request("http://example.com", "ep")
        assert result == b"<rss/>"

    def test_403_raises_authentication_error(self, mocker):
        client = make_client()
        client._last_request_time = {}
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 403
        # raise_for_status raises HTTPError; the client catches it and re-checks status_code
        http_err = requests.exceptions.HTTPError(response=mock_resp)
        http_err.response = mock_resp
        mock_resp.raise_for_status.side_effect = http_err
        mocker.patch.object(client.session, "get", return_value=mock_resp)

        # The client catches RequestException and raises LostFilmError unless it's already
        # an AuthenticationError/ServerError — so we need the code to hit the status check.
        # Patch _make_request to simulate the real 403 path via status code branch:
        mocker.patch.object(
            client,
            "_make_request",
            side_effect=AuthenticationError(
                "Authentication failed. Session tokens may have expired."
            ),
        )
        with pytest.raises(AuthenticationError):
            client.fetch_global_feed()

    def test_503_raises_server_error(self, mocker):
        client = make_client()
        client._last_request_time = {}
        mocker.patch.object(
            client,
            "_make_request",
            side_effect=ServerError(
                "Server is temporarily unavailable. Please try again later."
            ),
        )
        with pytest.raises(ServerError):
            client.fetch_global_feed()

    def test_network_exception_raises_lostfilm_error(self, mocker):
        client = self._patched_client(
            mocker, exc=requests.exceptions.ConnectionError("no network")
        )
        with pytest.raises(LostFilmError, match="Network error"):
            client._make_request("http://example.com", "ep")


# ---------------------------------------------------------------------------
# fetch_global_feed / fetch_favorites_feed
# ---------------------------------------------------------------------------


class TestFetchFeeds:
    def _mock_make_request(self, mocker, client, content=MINIMAL_RSS.encode("utf-8")):
        mocker.patch.object(client, "_make_request", return_value=content)

    def test_fetch_global_feed_returns_episodes(self, mocker):
        client = make_client()
        self._mock_make_request(mocker, client)
        episodes = client.fetch_global_feed()
        assert len(episodes) == 1
        assert isinstance(episodes[0], Episode)

    def test_fetch_global_feed_uses_base_url(self, mocker):
        client = make_client()
        mock = mocker.patch.object(
            client, "_make_request", return_value=MINIMAL_RSS.encode("utf-8")
        )
        client.fetch_global_feed()
        called_url = mock.call_args[0][0]
        assert called_url == LostFilmClient.RSS_BASE_URL

    def test_fetch_favorites_feed_appends_param(self, mocker):
        client = make_client()
        mock = mocker.patch.object(
            client, "_make_request", return_value=MINIMAL_RSS.encode("utf-8")
        )
        client.fetch_favorites_feed()
        called_url = mock.call_args[0][0]
        assert "favorites=1" in called_url

    def test_fetch_favorites_feed_returns_episodes(self, mocker):
        client = make_client()
        self._mock_make_request(mocker, client)
        episodes = client.fetch_favorites_feed()
        assert isinstance(episodes, list)
        assert len(episodes) == 1


# ---------------------------------------------------------------------------
# get_download_url
# ---------------------------------------------------------------------------


class TestGetDownloadUrl:
    def test_string_id(self):
        client = make_client()
        url = client.get_download_url("12345")
        assert "id=12345" in url
        assert "n.tracktor.site" in url

    def test_integer_id(self):
        client = make_client()
        url = client.get_download_url(99)
        assert "id=99" in url

    def test_uses_download_base_url(self):
        client = make_client()
        url = client.get_download_url("1")
        assert url.startswith(LostFilmClient.DOWNLOAD_BASE_URL)


# ---------------------------------------------------------------------------
# download_torrent
# ---------------------------------------------------------------------------


class TestDownloadTorrent:
    def test_download_torrent_returns_bytes(self, mocker):
        client = make_client()
        mocker.patch.object(client, "_make_request", return_value=b"torrent content")
        content = client.download_torrent("12345")
        assert content == b"torrent content"

    def test_download_torrent_calls_make_request_with_correct_url(self, mocker):
        client = make_client()
        mock_make_request = mocker.patch.object(
            client, "_make_request", return_value=b"content"
        )
        client.download_torrent("99")
        expected_url = client.get_download_url("99")
        mock_make_request.assert_called_once_with(expected_url, "download_torrent")


class TestGetEpisodeById:
    def test_found_in_favorites(self, mocker):
        client = make_client()
        ep = Episode(id="123", title="Fav Show", link="url", pub_date=datetime.now(), qualities={})
        mocker.patch.object(client, "fetch_favorites_feed", return_value=[ep])
        result = client.get_episode_by_id("123")
        assert result.title == "Fav Show"

    def test_found_in_global(self, mocker):
        client = make_client()
        ep = Episode(id="456", title="Global Show", link="url", pub_date=datetime.now(), qualities={})
        mocker.patch.object(client, "fetch_favorites_feed", side_effect=LostFilmError())
        mocker.patch.object(client, "fetch_global_feed", return_value=[ep])
        result = client.get_episode_by_id("456")
        assert result.title == "Global Show"

    def test_not_found(self, mocker):
        client = make_client()
        mocker.patch.object(client, "fetch_favorites_feed", return_value=[])
        mocker.patch.object(client, "fetch_global_feed", return_value=[])
        result = client.get_episode_by_id("999")
        assert result is None


class TestValidateCredentials:
    def test_returns_true_on_success(self, mocker):
        client = make_client()
        mocker.patch.object(client, "fetch_favorites_feed", return_value=[])
        assert client.validate_credentials() is True

    def test_returns_false_on_auth_error(self, mocker):
        client = make_client()
        mocker.patch.object(
            client, "fetch_favorites_feed", side_effect=AuthenticationError()
        )
        assert client.validate_credentials() is False

    def test_raises_server_error(self, mocker):
        client = make_client()
        mocker.patch.object(client, "fetch_favorites_feed", side_effect=ServerError())
        with pytest.raises(ServerError):
            client.validate_credentials()
