"""Tests for the Deluge integration, accessibility check, upload queue, retry logic, and status tracking."""

import unittest
from unittest.mock import MagicMock, patch

from lostfilm.deluge import DelugeClient


class TestDelugeAccessCheck(unittest.TestCase):
    """Tests for DelugeClient.check_access() and is_accessible()."""

    def setUp(self):
        self.client = DelugeClient(url="http://deluge:8112", password="secret_password")

    @patch("deluge_web_client.DelugeWebClient")
    def test_check_access_success(self, mock_web_client_cls):
        mock_instance = MagicMock()
        mock_web_client_cls.return_value = mock_instance
        mock_response = MagicMock()
        mock_response.result = True
        mock_instance.login.return_value = mock_response

        self.assertTrue(self.client.check_access())
        self.assertTrue(self.client.is_accessible())
        self.assertEqual(mock_instance.login.call_count, 2)
        self.assertEqual(mock_instance.close_session.call_count, 2)

    @patch("deluge_web_client.DelugeWebClient")
    def test_check_access_login_falsy_result(self, mock_web_client_cls):
        mock_instance = MagicMock()
        mock_web_client_cls.return_value = mock_instance
        mock_response = MagicMock()
        mock_response.result = False
        mock_instance.login.return_value = mock_response

        self.assertFalse(self.client.check_access())
        self.assertFalse(self.client.is_accessible())
        self.assertEqual(mock_instance.close_session.call_count, 2)

    @patch("deluge_web_client.DelugeWebClient")
    def test_check_access_exception_handled(self, mock_web_client_cls):
        mock_instance = MagicMock()
        mock_web_client_cls.return_value = mock_instance
        mock_instance.login.side_effect = ConnectionError("Cannot reach Deluge WebUI")

        self.assertFalse(self.client.check_access())
        self.assertFalse(self.client.is_accessible())


class TestDelugeUploadAndRetry(unittest.TestCase):
    """Tests for upload queue, retry attempts, and Telegram notifications."""

    def setUp(self):
        self.notifier = MagicMock()
        self.client = DelugeClient(
            url="http://deluge:8112",
            password="secret_password",
            notifier=self.notifier,
            max_retries=3,
            retry_delay=0.001,  # Fast retries for testing
        )

    @patch.object(DelugeClient, "check_access")
    @patch.object(DelugeClient, "_do_upload")
    def test_upload_success_first_try(self, mock_do_upload, mock_check_access):
        mock_check_access.return_value = True
        mock_do_upload.return_value = "hash1234567890"

        ok = self.client.upload_torrent_bytes(
            torrent_bytes=b"torrent_data",
            title="House of the Dragon S02E01",
            torrent_url="https://example.com/hotd.torrent",
        )

        self.assertTrue(ok)
        mock_check_access.assert_called_once()
        mock_do_upload.assert_called_once_with(
            b"torrent_data", title="House of the Dragon S02E01"
        )
        self.assertEqual(len(self.client.upload_queue), 0)
        self.assertIn("hash1234567890", self.client.tracked_torrents)
        self.notifier.send_torrent_status_update.assert_called_once_with(
            title="House of the Dragon S02E01",
            status="added",
            details=None,
        )

    @patch.object(DelugeClient, "check_access")
    @patch.object(DelugeClient, "_do_upload")
    @patch("time.sleep")
    def test_upload_queued_and_succeeds_on_second_try(
        self, mock_sleep, mock_do_upload, mock_check_access
    ):
        # Try 1: inaccessible. Try 2: accessible.
        mock_check_access.side_effect = [False, True]
        mock_do_upload.return_value = "hash_second_try"

        ok = self.client.upload_torrent_bytes(
            torrent_bytes=b"dummy_bytes",
            title="Slow Horses S04E01",
        )

        self.assertTrue(ok)
        self.assertEqual(mock_check_access.call_count, 2)
        mock_sleep.assert_called_once_with(0.001)
        self.assertEqual(len(self.client.upload_queue), 0)
        self.assertIn("hash_second_try", self.client.tracked_torrents)
        self.notifier.send_torrent_status_update.assert_called_once_with(
            title="Slow Horses S04E01",
            status="added",
            details=None,
        )

    @patch.object(DelugeClient, "check_access")
    @patch.object(DelugeClient, "_do_upload")
    @patch("time.sleep")
    def test_upload_queued_and_succeeds_on_third_try(
        self, mock_sleep, mock_do_upload, mock_check_access
    ):
        # Try 1: False, Try 2: False, Try 3: True
        mock_check_access.side_effect = [False, False, True]
        mock_do_upload.return_value = "hash_third_try"

        ok = self.client.upload_torrent_bytes(
            torrent_bytes=b"dummy_bytes",
            title="Severance S02E01",
        )

        self.assertTrue(ok)
        self.assertEqual(mock_check_access.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertEqual(len(self.client.upload_queue), 0)
        self.assertIn("hash_third_try", self.client.tracked_torrents)
        self.notifier.send_torrent_status_update.assert_called_once_with(
            title="Severance S02E01",
            status="added",
            details=None,
        )

    @patch.object(DelugeClient, "check_access")
    @patch.object(DelugeClient, "_do_upload")
    @patch("time.sleep")
    def test_upload_queued_and_fails_after_three_tries(
        self, mock_sleep, mock_do_upload, mock_check_access
    ):
        # All 3 tries fail access check
        mock_check_access.return_value = False

        ok = self.client.upload_torrent_bytes(
            torrent_bytes=b"dummy_bytes",
            title="Fallout S01E01",
        )

        self.assertFalse(ok)
        # 1 initial + 2 retries = 3 attempts total
        self.assertEqual(mock_check_access.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertEqual(len(self.client.upload_queue), 0)
        self.assertEqual(len(self.client.tracked_torrents), 0)
        self.notifier.send_torrent_status_update.assert_called_once_with(
            title="Fallout S01E01",
            status="fail",
            details="Deluge not accessible after 3 tries",
        )

    @patch("lostfilm.deluge.requests.get")
    @patch.object(DelugeClient, "upload_torrent_bytes")
    def test_add_torrent_url_downloads_and_calls_upload(
        self, mock_upload_bytes, mock_get
    ):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.content = b"downloaded_torrent_bytes"
        mock_get.return_value = mock_resp
        mock_upload_bytes.return_value = True

        ok = self.client.add_torrent_url(
            torrent_url="https://example.com/ep.torrent",
            lf_cookies={"uid": "1", "usess": "abc"},
            title="The Bear S03E01",
        )

        self.assertTrue(ok)
        mock_get.assert_called_once_with(
            "https://example.com/ep.torrent",
            cookies={"uid": "1", "usess": "abc"},
            headers={"User-Agent": mock_get.call_args[1]["headers"]["User-Agent"]},
            timeout=30,
        )
        mock_upload_bytes.assert_called_once_with(
            torrent_bytes=b"downloaded_torrent_bytes",
            title="The Bear S03E01",
            torrent_url="https://example.com/ep.torrent",
        )

    @patch("lostfilm.deluge.requests.get")
    def test_add_torrent_url_download_failure_notifies_fail(self, mock_get):
        import requests

        mock_get.side_effect = requests.RequestException("404 Not Found")

        ok = self.client.add_torrent_url(
            torrent_url="https://example.com/ep.torrent",
            title="Failed Download Show",
        )

        self.assertFalse(ok)
        self.notifier.send_torrent_status_update.assert_called_once_with(
            title="Failed Download Show",
            status="fail",
            details="Download failed: 404 Not Found",
        )


class TestDelugePeriodicStatusTracking(unittest.TestCase):
    """Tests for periodically checking torrent status and sending Telegram notifications."""

    def setUp(self):
        self.notifier = MagicMock()
        self.client = DelugeClient(
            url="http://deluge:8112",
            password="secret_password",
            notifier=self.notifier,
        )
        self.client.track_torrent("hash_1", title="Episode 1")
        self.client.track_torrent("hash_2", title="Episode 2")

    @patch("deluge_web_client.DelugeWebClient")
    def test_check_torrents_status_downloaded(self, mock_web_client_cls):
        mock_instance = MagicMock()
        mock_web_client_cls.return_value = mock_instance
        mock_instance.login.return_value = MagicMock(result=True)

        # Episode 1 completed seeding (downloaded)
        mock_instance.get_torrents_status.return_value = MagicMock(
            result={
                "hash_1": {"state": "Seeding", "progress": 100.0, "is_finished": True},
                "hash_2": {
                    "state": "Downloading",
                    "progress": 45.0,
                    "is_finished": False,
                },
            }
        )

        results = self.client.check_torrents_status()

        self.assertEqual(results, {"hash_1": "downloaded"})
        # hash_1 was removed after finishing
        self.assertNotIn("hash_1", self.client.tracked_torrents)
        # hash_2 is still tracked
        self.assertIn("hash_2", self.client.tracked_torrents)
        self.notifier.send_torrent_status_update.assert_called_once_with(
            title="Episode 1",
            status="downloaded",
            details=None,
        )

    @patch("deluge_web_client.DelugeWebClient")
    def test_check_torrents_status_fail(self, mock_web_client_cls):
        mock_instance = MagicMock()
        mock_web_client_cls.return_value = mock_instance
        mock_instance.login.return_value = MagicMock(result=True)

        mock_instance.get_torrents_status.return_value = MagicMock(
            result={
                "hash_1": {
                    "state": "Downloading",
                    "progress": 10.0,
                    "is_finished": False,
                },
                "hash_2": {"state": "Error", "message": "Tracker returned error 500"},
            }
        )

        results = self.client.check_torrents_status()

        self.assertEqual(results, {"hash_2": "fail"})
        self.assertNotIn("hash_2", self.client.tracked_torrents)
        self.assertIn("hash_1", self.client.tracked_torrents)
        self.notifier.send_torrent_status_update.assert_called_once_with(
            title="Episode 2",
            status="fail",
            details="Tracker returned error 500",
        )

    def test_start_and_stop_status_checker(self):
        self.client.start_status_checker(interval=0.1)
        self.assertIsNotNone(self.client._checker_thread)
        self.assertTrue(self.client._checker_thread.is_alive())

        self.client.stop_status_checker()
        self.assertFalse(self.client._checker_thread.is_alive())


class TestTelegramNotifierStatusUpdates(unittest.TestCase):
    """Tests for TelegramNotifier.send_message and send_torrent_status_update."""

    @patch("lostfilm.telegram.requests.post")
    def test_send_torrent_status_update_added(self, mock_post):
        from lostfilm.telegram import TelegramNotifier

        notifier = TelegramNotifier(bot_token="test_token", chat_id="12345")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        ok = notifier.send_torrent_status_update("Severance S02E01", "added")

        self.assertTrue(ok)
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["data"]
        self.assertEqual(payload["chat_id"], 12345)
        self.assertIn("Torrent added to Deluge", payload["text"])
        self.assertIn("Severance S02E01", payload["text"])

    @patch("lostfilm.telegram.requests.post")
    def test_send_torrent_status_update_downloaded(self, mock_post):
        from lostfilm.telegram import TelegramNotifier

        notifier = TelegramNotifier(bot_token="test_token", chat_id="12345")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        ok = notifier.send_torrent_status_update("Severance S02E01", "downloaded")

        self.assertTrue(ok)
        payload = mock_post.call_args[1]["data"]
        self.assertIn("Torrent downloaded", payload["text"])
        self.assertIn("Severance S02E01", payload["text"])

    @patch("lostfilm.telegram.requests.post")
    def test_send_torrent_status_update_fail(self, mock_post):
        from lostfilm.telegram import TelegramNotifier

        notifier = TelegramNotifier(bot_token="test_token", chat_id="12345")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        ok = notifier.send_torrent_status_update(
            "Severance S02E01", "fail", details="Timeout"
        )

        self.assertTrue(ok)
        payload = mock_post.call_args[1]["data"]
        self.assertIn("Torrent fail", payload["text"])
        self.assertIn("Timeout", payload["text"])
