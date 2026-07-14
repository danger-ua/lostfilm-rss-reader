"""Tests for the Telegram notifier, including a live integration test."""

import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from lostfilm.models import Episode
from lostfilm.telegram import TelegramNotifier


def _make_episode(**kwargs) -> Episode:
    defaults = dict(
        id="42",
        title="Test Show (S01E01)",
        link="https://www.lostfilm.tv/series/Test_Show/season_1/episode_1/",
        pub_date=datetime(2026, 3, 4, 17, 0, 0),
        qualities={"1080p": "https://example.com/download"}
    )
    defaults.update(kwargs)
    return Episode(**defaults)


class TestTelegramNotifierDisabled(unittest.TestCase):
    """
    Notifier with missing credentials should be a no-op.

    setUp/tearDown temporarily remove real credentials from the environment so
    that a live .env loaded by conftest.py doesn't bleed into these unit tests.
    """

    _ENV_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")

    def setUp(self):
        # Stash and remove any real credentials so we get a clean slate.
        self._saved = {k: os.environ.pop(k, None) for k in self._ENV_KEYS}

    def tearDown(self):
        # Restore the original values (or delete if they were absent).
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_disabled_when_no_token(self):
        notifier = TelegramNotifier(bot_token=None, chat_id="123")
        self.assertFalse(notifier.is_enabled())

    @patch("lostfilm.telegram.requests.get")
    def test_disabled_when_no_chat_id_and_no_updates(self, mock_get):
        """Token present but getUpdates returns nothing — notifier stays disabled."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"ok": True, "result": []}
        mock_get.return_value = mock_response

        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        notifier = TelegramNotifier(bot_token=telegram_token, chat_id=None)
        self.assertFalse(notifier.is_enabled())

    def test_disabled_when_both_missing(self):
        notifier = TelegramNotifier(bot_token=None, chat_id=None)
        self.assertFalse(notifier.is_enabled())

    def test_send_returns_true_when_disabled(self):
        """Disabled notifier should silently succeed (return True)."""
        notifier = TelegramNotifier(bot_token=None, chat_id=None)
        result = notifier.send_episode_notification(_make_episode())
        self.assertTrue(result)


class TestTelegramNotifierEnabled(unittest.TestCase):
    """Notifier with valid credentials — HTTP calls are mocked."""

    def setUp(self):
        self.notifier = TelegramNotifier(bot_token="fake_token", chat_id="99999")
        self.notifier._find_poster_url = MagicMock(return_value=None)

    def test_enabled_with_credentials(self):
        self.assertTrue(self.notifier.is_enabled())

    @patch("lostfilm.telegram.requests.post")
    def test_send_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.notifier.send_episode_notification(_make_episode())

        self.assertTrue(result)
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        self.assertIn("fake_token", call_kwargs[0][0])  # URL contains token
        payload = call_kwargs[1]["data"]
        self.assertEqual(payload["chat_id"], 99999)
        self.assertIn("Test Show (S01E01)", payload["text"])
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertEqual(payload["link_preview_options"], '{"is_disabled": true}')

    @patch("lostfilm.telegram.requests.post")
    def test_send_failure_returns_false(self, mock_post):
        import requests as req

        mock_post.side_effect = req.RequestException("connection error")

        result = self.notifier.send_episode_notification(_make_episode())

        self.assertFalse(result)

    @patch("lostfilm.telegram.requests.post")
    def test_send_http_error_returns_false(self, mock_post):
        import requests as req

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req.HTTPError("404 Not Found")
        mock_post.return_value = mock_response

        result = self.notifier.send_episode_notification(_make_episode())

        self.assertFalse(result)

    @patch("lostfilm.telegram.requests.post")
    def test_message_contains_download_link(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        episode = _make_episode(qualities={"720p": "https://example.com/download"})
        self.notifier.send_episode_notification(episode)

        payload = mock_post.call_args[1]["data"]
        self.assertIn("https://example.com/download", payload["text"])


class TestFetchChatId(unittest.TestCase):
    """Unit tests for the auto-discovery of chat_id via getUpdates."""

    def _notifier_with_token(self) -> TelegramNotifier:
        """Return a notifier that already has a token + chat_id (no HTTP call on init)."""
        return TelegramNotifier(bot_token="fake_token", chat_id="already_set")

    @patch("lostfilm.telegram.requests.get")
    def test_fetch_chat_id_success(self, mock_get):
        """fetch_chat_id returns the chat id from the most recent message."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "ok": True,
            "result": [
                {"update_id": 1, "message": {"chat": {"id": 11111}}},
                {"update_id": 2, "message": {"chat": {"id": 22222}}},
            ],
        }
        mock_get.return_value = mock_response

        notifier = self._notifier_with_token()
        chat_id = notifier.fetch_chat_id()

        self.assertEqual(chat_id, "22222")  # most recent (reversed)
        # 2 calls: 1 from _verify_bot in __init__, 1 from fetch_chat_id
        self.assertEqual(mock_get.call_count, 2)
        self.assertIn("fake_token", mock_get.call_args[0][0])

    @patch("lostfilm.telegram.requests.get")
    def test_fetch_chat_id_from_channel_post(self, mock_get):
        """chat_id is also discovered from channel_post updates."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "ok": True,
            "result": [
                {"update_id": 1, "channel_post": {"chat": {"id": -100987654321}}},
            ],
        }
        mock_get.return_value = mock_response

        notifier = self._notifier_with_token()
        chat_id = notifier.fetch_chat_id()

        self.assertEqual(chat_id, "-100987654321")
        self.assertEqual(mock_get.call_count, 2)

    @patch("lostfilm.telegram.requests.get")
    def test_fetch_chat_id_empty_updates_returns_none(self, mock_get):
        """Returns None when getUpdates result is empty."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"ok": True, "result": []}
        mock_get.return_value = mock_response

        notifier = self._notifier_with_token()
        chat_id = notifier.fetch_chat_id()

        self.assertIsNone(chat_id)
        self.assertEqual(mock_get.call_count, 2)

    @patch("lostfilm.telegram.requests.get")
    def test_fetch_chat_id_network_error_returns_none(self, mock_get):
        """Returns None gracefully on network failure."""
        import requests as req

        mock_get.side_effect = req.RequestException("timeout")

        notifier = self._notifier_with_token()
        chat_id = notifier.fetch_chat_id()

        self.assertIsNone(chat_id)
        self.assertEqual(mock_get.call_count, 2)

    def test_fetch_chat_id_no_token_returns_none(self):
        """Returns None immediately when bot_token is not set."""
        notifier = TelegramNotifier(bot_token=None, chat_id=None)
        self.assertIsNone(notifier.fetch_chat_id())

    @patch("lostfilm.telegram.requests.get")
    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake_token"}, clear=False)
    def test_auto_discovery_on_init(self, mock_get):
        """When chat_id is None but token is set, __init__ calls fetch_chat_id.

        TELEGRAM_CHAT_ID is patched out of the env so the constructor is forced
        to resolve the chat_id via getUpdates (the mocked HTTP call), not from env.
        """
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "ok": True,
            "result": [{"update_id": 1, "message": {"chat": {"id": 55555}}}],
        }
        mock_get.return_value = mock_response

        # Remove TELEGRAM_CHAT_ID for the duration of this test.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            notifier = TelegramNotifier(bot_token="fake_token", chat_id=None)

        self.assertTrue(notifier.is_enabled())
        self.assertEqual(notifier.chat_id, "55555")
        # 1 from _verify_bot, 1 from fetch_chat_id (which is called in __init__)
        self.assertEqual(mock_get.call_count, 2)


@unittest.skipUnless(
    os.getenv("TELEGRAM_BOT_TOKEN"),
    "Skipped: set TELEGRAM_BOT_TOKEN in .env to run chat_id discovery",
)
class TestTelegramDiscoverChatId(unittest.TestCase):
    """
    Live auto-discovery test — only requires TELEGRAM_BOT_TOKEN.

    Use this to find your TELEGRAM_CHAT_ID when it is not yet known.
    Before running, open a chat with your bot in Telegram and send any
    message (e.g. /start).  The discovered ID will be printed to stdout.

    Run:
        uv run pytest tests/test_telegram.py::TestTelegramDiscoverChatId -v -s

    Or via Makefile:
        make discover-chat-id
    """

    def test_discover_and_print_chat_id(self):
        """
        Calls getUpdates with the real bot token and prints the chat ID.
        The bot must have received at least one message beforehand.
        """
        bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            notifier = TelegramNotifier(bot_token=bot_token, chat_id=None)

        if notifier.chat_id is None:
            print(
                "\n  ⚠️ Could not discover chat_id. "
                "Make sure you sent a message to the bot first (e.g. /start), then retry."
            )
            return
        self.assertTrue(notifier.is_enabled())
        print(f"\n\n  ✅ Auto-discovered TELEGRAM_CHAT_ID={notifier.chat_id}")
        print(f"  Add this to your .env file:\n  TELEGRAM_CHAT_ID={notifier.chat_id}\n")


@unittest.skipUnless(
    os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"),
    "Skipped: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to run live test",
)
class TestTelegramNotifierLive(unittest.TestCase):
    """
    Live send test — requires both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.

    Run:
        uv run pytest tests/test_telegram.py::TestTelegramNotifierLive -v

    Or via Makefile:
        make test-telegram-live
    """

    def test_send_test_notification(self):
        """Sends a  test notification to the configured Telegram chat."""
        bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
        chat_id = os.environ["TELEGRAM_CHAT_ID"]

        notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
        self.assertTrue(
            notifier.is_enabled(), "Notifier should be enabled with real credentials"
        )

        episode = Episode(
            id="test-000",
            title="Медведь (The Bear). (S05E08) - Live Test Poster",
            link="https://github.com",
            pub_date=datetime.now(),
            qualities={"1080p": "https://example.com/1080p"}
        )

        result = notifier.send_episode_notification(episode)
        self.assertTrue(
            result,
            "Live Telegram notification failed — check your BOT_TOKEN and CHAT_ID",
        )

class TestTelegramPoster(unittest.TestCase):
    def test_normalize_name(self):
        from lostfilm.telegram import _normalize_name
        self.assertEqual(_normalize_name("The Bear"), "thebear")
        self.assertEqual(_normalize_name("Медведь"), "медведь")
        self.assertEqual(_normalize_name("Show (US)"), "showus")

    def test_extract_series_names(self):
        from lostfilm.telegram import _extract_series_names
        ru, en = _extract_series_names("Я тебя отыщу (I Will Find You). Эпизод четвёртый (S01E04)")
        self.assertEqual(ru, "Я тебя отыщу")
        self.assertEqual(en, "I Will Find You")

        ru, en = _extract_series_names("Медведь (The Bear). (S05E08)")
        self.assertEqual(ru, "Медведь")
        self.assertEqual(en, "The Bear")

        ru, en = _extract_series_names("No Parentheses Title S01E01")
        self.assertIsNone(ru)
        self.assertIsNone(en)

    @patch("lostfilm.telegram.requests.get")
    def test_find_poster_url_success(self, mock_get):
        # Mock search response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
        <div class="row-search">
            <a href="/series/The_Bear" class="no-decoration">
                <div class="picture-box">
                    <img src="/Static/Images/738/Posters/image.jpg" class="thumb">
                </div>
                <div class="body">
                    <div class="name-ru">Медведь</div>
                    <div class="name-en">The Bear</div>
                </div>
            </a>
        </div>
        """
        mock_get.return_value = mock_response

        # Mock requests.head for verifying poster.jpg
        with patch("lostfilm.telegram.requests.head") as mock_head:
            mock_head_res = MagicMock()
            mock_head_res.status_code = 200
            mock_head.return_value = mock_head_res

            notifier = TelegramNotifier(bot_token="fake", chat_id="123")
            poster_url, _ = notifier._find_show_info("Медведь (The Bear). (S05E08)")
            self.assertEqual(poster_url, "https://www.lostfilm.tv/Static/Images/738/Posters/poster.jpg")
            mock_head.assert_called_once_with(
                "https://www.lostfilm.tv/Static/Images/738/Posters/poster.jpg",
                headers=unittest.mock.ANY,
                timeout=2
            )

    @patch("lostfilm.telegram.requests.get")
    def test_find_poster_url_fallback_to_image(self, mock_get):
        # Mock search response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
        <div class="row-search">
            <a href="/series/The_Bear" class="no-decoration">
                <div class="picture-box">
                    <img src="/Static/Images/738/Posters/image.jpg" class="thumb">
                </div>
                <div class="body">
                    <div class="name-ru">Медведь</div>
                    <div class="name-en">The Bear</div>
                </div>
            </a>
        </div>
        """
        mock_get.return_value = mock_response

        # Mock requests.head failing for poster.jpg (e.g. 404)
        with patch("lostfilm.telegram.requests.head") as mock_head:
            mock_head_res = MagicMock()
            mock_head_res.status_code = 404
            mock_head.return_value = mock_head_res

            notifier = TelegramNotifier(bot_token="fake", chat_id="123")
            poster_url, _ = notifier._find_show_info("Медведь (The Bear). (S05E08)")
            self.assertEqual(poster_url, "https://www.lostfilm.tv/Static/Images/738/Posters/image.jpg")

    @patch("lostfilm.telegram.requests.post")
    def test_send_notification_with_photo(self, mock_post):
        notifier = TelegramNotifier(bot_token="fake", chat_id="123")
        notifier._find_show_info = MagicMock(return_value=("https://example.com/poster.jpg", None))

        mock_post_res = MagicMock()
        mock_post_res.raise_for_status.return_value = None
        mock_post.return_value = mock_post_res

        episode = _make_episode(title="Медведь (The Bear). (S05E08)")
        result = notifier.send_episode_notification(episode)

        self.assertTrue(result)
        mock_post.assert_called_once()
        call_url, call_kwargs = mock_post.call_args
        self.assertIn("sendPhoto", call_url[0])
        self.assertEqual(call_kwargs["data"]["photo"], "https://example.com/poster.jpg")
        self.assertIn("Медведь (The Bear)", call_kwargs["data"]["caption"])

    @patch("lostfilm.telegram.requests.post")
    def test_send_notification_photo_fallback(self, mock_post):
        notifier = TelegramNotifier(bot_token="fake", chat_id="123")
        notifier._find_poster_url = MagicMock(return_value="https://example.com/poster.jpg")

        # Mock sendPhoto failing, but sendMessage succeeding
        import requests as req
        def mock_post_side_effect(url, *args, **kwargs):
            if "sendPhoto" in url:
                raise req.RequestException("failed to send photo")
            mock_res = MagicMock()
            mock_res.raise_for_status.return_value = None
            return mock_res

        mock_post.side_effect = mock_post_side_effect

        episode = _make_episode(title="Медведь (The Bear). (S05E08)")
        result = notifier.send_episode_notification(episode)

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)
        # First call was sendPhoto
        first_call = mock_post.call_args_list[0]
        self.assertIn("sendPhoto", first_call[0][0])
        # Second call was sendMessage
        second_call = mock_post.call_args_list[1]
        self.assertIn("sendMessage", second_call[0][0])
        self.assertIn("Медведь (The Bear)", second_call[1]["data"]["text"])


if __name__ == "__main__":
    unittest.main()
