"""Deluge Web Client integration for adding torrents automatically."""

import logging
import os
import threading
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class DelugeClient:
    """
    Thin wrapper around the Deluge Web UI JSON-RPC API.

    Connects to Deluge via its WebUI endpoint (DELUGE_URL) using a password
    (DELUGE_PASS). Torrents are submitted as raw bytes, so we first download
    the .torrent file from LostFilm using the user's session cookies.
    """

    def __init__(
        self,
        url: str | None = None,
        password: str | None = None,
        notifier: Any | None = None,
        max_retries: int = 3,
        retry_delay: float = 30.0,
        status_check_interval: float = 10.0,
    ) -> None:
        self.url = (url or os.getenv("DELUGE_URL", "")).rstrip("/")
        self.password = password or os.getenv("DELUGE_PASS", "")
        self.notifier = notifier
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.status_check_interval = status_check_interval

        self.upload_queue: list[dict[str, Any]] = []
        self.tracked_torrents: dict[str, dict[str, Any]] = {}
        self._checker_thread: threading.Thread | None = None
        self._stop_checker_event = threading.Event()

        if not self.url:
            raise ValueError("DELUGE_URL is not set.")

    def is_configured(self) -> bool:
        """Return True if both URL and password are provided."""
        return bool(self.url and self.password is not None)

    def check_access(self) -> bool:
        """
        Check if Deluge Web UI is accessible and connected to a daemon.

        Returns:
            ``True`` if Deluge is accessible, ``False`` otherwise.
        """
        try:
            from deluge_web_client import DelugeWebClient  # type: ignore[import-untyped]

            client = DelugeWebClient(url=self.url, password=self.password)
            try:
                res = client.login()
                return bool(res and res.result)
            finally:
                try:
                    client.close_session()
                except Exception as e:
                    logger.debug("Error closing Deluge session: %s", e)
        except Exception as e:
            logger.warning("Deluge access check failed: %s", e)
            return False

    def is_accessible(self) -> bool:
        """Return True if Deluge is accessible (alias for check_access)."""
        return self.check_access()

    def _notify_status(
        self,
        title: str | None,
        status: str,
        details: str | None = None,
        torrent_id: str | None = None,
    ) -> bool:
        """
        Notify Telegram about torrent status update ('added', 'downloaded', 'fail').
        """
        display_title = title or torrent_id or "Unknown torrent"
        logger.info(
            "Torrent status update: '%s' -> %s%s",
            display_title,
            status,
            f" ({details})" if details else "",
        )
        if not self.notifier:
            return False

        if hasattr(self.notifier, "send_torrent_status_update"):
            return bool(
                self.notifier.send_torrent_status_update(
                    title=display_title,
                    status=status,
                    details=details,
                )
            )
        elif hasattr(self.notifier, "send_message"):
            if status == "added":
                msg = f"📥 <b>Torrent added to Deluge:</b>\n{display_title}"
            elif status == "downloaded":
                msg = f"🎉 <b>Torrent downloaded:</b>\n{display_title}"
            elif status == "fail":
                reason = f"\n<i>{details}</i>" if details else ""
                msg = f"❌ <b>Torrent fail:</b>\n{display_title}{reason}"
            else:
                msg = f"ℹ️ <b>Torrent status ({status}):</b>\n{display_title}"
            return bool(self.notifier.send_message(msg))
        return False

    def track_torrent(self, torrent_id: str, title: str | None = None) -> None:
        """Add a torrent to the periodic status tracking list."""
        self.tracked_torrents[torrent_id] = {
            "title": title or torrent_id,
            "status": "added",
            "added_at": time.time(),
        }

    def _do_upload(
        self,
        torrent_bytes: bytes,
        title: str | None = None,
    ) -> str | None:
        """
        Upload torrent bytes to Deluge WebUI.

        Returns:
            Torrent info_hash string on success, None on failure.
        """
        import os as _os
        import tempfile

        from deluge_web_client import DelugeWebClient, TorrentOptions  # type: ignore[import-untyped]

        torrent_options = TorrentOptions(label="serials")
        with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tmp:
            tmp.write(torrent_bytes)
            tmp_path = tmp.name

        try:
            client = DelugeWebClient(url=self.url, password=self.password)
            try:
                login_resp = client.login()
                if not login_resp or not login_resp.result:
                    logger.warning("Deluge login failed during upload: %s", login_resp)
                    return None
                result = client.upload_torrent(
                    torrent_path=tmp_path,
                    torrent_options=torrent_options,
                )
            finally:
                try:
                    client.close_session()
                except Exception as e:
                    logger.debug("Error closing Deluge session: %s", e)

            if result and result.result:
                if isinstance(result.result, bool):
                    return f"torrent_{int(time.time())}"
                return str(result.result)
            else:
                logger.warning(
                    "Deluge responded but upload result was falsy: %s", result
                )
                return None
        except Exception as e:
            logger.error("Deluge upload exception for '%s': %s", title, e)
            return None
        finally:
            if _os.path.exists(tmp_path):
                _os.unlink(tmp_path)

    def upload_torrent_bytes(
        self,
        torrent_bytes: bytes,
        title: str | None = None,
        torrent_url: str = "",
    ) -> bool:
        """
        Upload torrent bytes to Deluge.

        Checks Deluge access first. If inaccessible, adds to the upload queue
        and retries up to max_retries with sleep between tries.
        """
        # Try immediate upload if Deluge is accessible
        if self.check_access():
            info_hash = self._do_upload(torrent_bytes, title=title)
            if info_hash:
                if title:
                    logger.info(
                        "Torrent successfully added to Deluge: %s (%s)",
                        title,
                        torrent_url,
                    )
                else:
                    logger.info("Torrent successfully added to Deluge: %s", torrent_url)
                self._notify_status(title, "added", torrent_id=info_hash)
                self.track_torrent(info_hash, title=title)
                return True

        # Deluge is not accessible or initial upload failed: add to queue and retry
        queue_item: dict[str, Any] = {
            "torrent_bytes": torrent_bytes,
            "title": title,
            "torrent_url": torrent_url,
            "added_at": time.time(),
            "attempts": 1,
        }
        self.upload_queue.append(queue_item)
        logger.warning(
            "Deluge is not accessible. Added '%s' to upload queue. Retrying upload (max %d tries, interval %ss)...",
            title or torrent_url,
            self.max_retries,
            self.retry_delay,
        )

        for attempt in range(2, self.max_retries + 1):
            time.sleep(self.retry_delay)
            queue_item["attempts"] = attempt
            logger.info(
                "Retrying Deluge access and upload for '%s' (try %d/%d)...",
                title or torrent_url,
                attempt,
                self.max_retries,
            )
            if self.check_access():
                info_hash = self._do_upload(torrent_bytes, title=title)
                if info_hash:
                    if queue_item in self.upload_queue:
                        self.upload_queue.remove(queue_item)
                    if title:
                        logger.info(
                            "Torrent successfully added to Deluge: %s (%s)",
                            title,
                            torrent_url,
                        )
                    else:
                        logger.info(
                            "Torrent successfully added to Deluge: %s",
                            torrent_url,
                        )
                    self._notify_status(title, "added", torrent_id=info_hash)
                    self.track_torrent(info_hash, title=title)
                    return True

        # Exhausted all attempts
        if queue_item in self.upload_queue:
            self.upload_queue.remove(queue_item)
        logger.error(
            "Deluge was not accessible after %d tries for '%s'",
            self.max_retries,
            title or torrent_url,
        )
        self._notify_status(
            title,
            "fail",
            details=f"Deluge not accessible after {self.max_retries} tries",
        )
        return False

    def add_torrent_file(
        self,
        torrent_path: str,
        title: str | None = None,
    ) -> bool:
        """
        Add a local .torrent file to Deluge with accessibility check and retries.
        """
        try:
            with open(torrent_path, "rb") as f:
                torrent_bytes = f.read()
        except OSError as e:
            logger.error("Failed to read torrent file %s: %s", torrent_path, e)
            self._notify_status(title, "fail", details=f"Cannot read file: {e}")
            return False

        display_title = title or os.path.basename(torrent_path)
        return self.upload_torrent_bytes(
            torrent_bytes=torrent_bytes,
            title=display_title,
            torrent_url=torrent_path,
        )

    def add_torrent_url(
        self,
        torrent_url: str,
        lf_cookies: dict | None = None,
        title: str | None = None,
    ) -> bool:
        """
        Download a .torrent file from *torrent_url* and add it to Deluge.

        Args:
            torrent_url: The LostFilm download URL for the .torrent file.
            lf_cookies: Optional dict of LostFilm session cookies
                        (``{"uid": ..., "usess": ...}``) used to authenticate
                        the download request.
            title: Optional episode or release title for logging.

        Returns:
            ``True`` if the torrent was added successfully, ``False`` otherwise.
        """
        # --- 1. Download the .torrent bytes from LostFilm ---
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            resp = requests.get(
                torrent_url,
                cookies=lf_cookies or {},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            torrent_bytes = resp.content
            logger.debug(
                "Downloaded torrent bytes (%d bytes) from %s",
                len(torrent_bytes),
                torrent_url,
            )
        except requests.RequestException as e:
            logger.error("Failed to download torrent from %s: %s", torrent_url, e)
            self._notify_status(title, "fail", details=f"Download failed: {e}")
            return False

        # --- 2. Upload to Deluge with accessibility check and retry queue ---
        return self.upload_torrent_bytes(
            torrent_bytes=torrent_bytes,
            title=title,
            torrent_url=torrent_url,
        )

    def check_torrents_status(self) -> dict[str, str]:
        """
        Check the status of tracked torrents in Deluge.
        Sends Telegram notifications for status updates ('downloaded', 'fail').

        Returns:
            Dict mapping torrent_id to new status ('downloaded', 'fail').
        """
        if not self.tracked_torrents:
            return {}

        results: dict[str, str] = {}
        try:
            from deluge_web_client import DelugeWebClient  # type: ignore[import-untyped]

            client = DelugeWebClient(url=self.url, password=self.password)
            try:
                login_resp = client.login()
                if not login_resp or not login_resp.result:
                    logger.warning("Could not login to Deluge to check torrent status.")
                    return {}

                all_torrents_status: dict[str, Any] | None = None
                try:
                    resp_all = client.get_torrents_status(
                        keys=["state", "progress", "is_finished", "message", "error"]
                    )
                    if resp_all and isinstance(resp_all.result, dict):
                        all_torrents_status = resp_all.result
                except Exception as e:
                    logger.debug(
                        "get_torrents_status failed, falling back to individual query: %s",
                        e,
                    )

                for tid in list(self.tracked_torrents.keys()):
                    info = self.tracked_torrents.get(tid)
                    if not info:
                        continue
                    title = info.get("title")

                    st_data: dict[str, Any] | None = None
                    if all_torrents_status and tid in all_torrents_status:
                        st_data = all_torrents_status[tid]
                    else:
                        try:
                            resp = client.get_torrent_status(
                                torrent_id=tid,
                                keys=[
                                    "state",
                                    "progress",
                                    "is_finished",
                                    "message",
                                    "error",
                                ],
                            )
                            if resp and isinstance(resp.result, dict):
                                st_data = resp.result
                        except Exception as e:
                            logger.debug(
                                "Error querying torrent status for %s: %s", tid, e
                            )

                    if not st_data:
                        continue

                    state = str(st_data.get("state", "")).lower()
                    progress = float(st_data.get("progress", 0.0))
                    is_finished = bool(st_data.get("is_finished", False))

                    if (
                        state == "seeding" or is_finished or progress >= 100.0
                    ) and info.get("status") != "downloaded":
                        info["status"] = "downloaded"
                        self._notify_status(title, "downloaded", torrent_id=tid)
                        results[tid] = "downloaded"
                    elif state == "error" and info.get("status") != "fail":
                        info["status"] = "fail"
                        err_msg = (
                            st_data.get("message")
                            or st_data.get("error")
                            or "Torrent entered Error state"
                        )
                        self._notify_status(
                            title, "fail", details=str(err_msg), torrent_id=tid
                        )
                        results[tid] = "fail"
            finally:
                try:
                    client.close_session()
                except Exception as e:
                    logger.debug("Error closing Deluge session: %s", e)
        except Exception as e:
            logger.warning("Failed to connect to Deluge during status check: %s", e)

        # Cleanup torrents that reached terminal states
        finished_ids = [
            tid
            for tid, info in list(self.tracked_torrents.items())
            if info.get("status") in ("downloaded", "fail")
        ]
        for tid in finished_ids:
            self.tracked_torrents.pop(tid, None)

        return results

    def start_status_checker(self, interval: float | None = None) -> None:
        """Start a background daemon thread that checks torrent status periodically."""
        if self._checker_thread and self._checker_thread.is_alive():
            logger.warning("Torrent status checker thread is already running.")
            return

        interval = interval or self.status_check_interval
        self._stop_checker_event.clear()

        def _worker() -> None:
            logger.info(
                "Deluge status checker thread started (interval=%.1fs).", interval
            )
            while not self._stop_checker_event.is_set():
                try:
                    self.check_torrents_status()
                except Exception as e:
                    logger.error("Error in Deluge status checker worker: %s", e)
                self._stop_checker_event.wait(timeout=interval)
            logger.info("Deluge status checker thread stopped.")

        self._checker_thread = threading.Thread(
            target=_worker,
            name="deluge-status-checker",
            daemon=True,
        )
        self._checker_thread.start()

    def stop_status_checker(self) -> None:
        """Stop the background status checker thread."""
        self._stop_checker_event.set()
        if self._checker_thread and self._checker_thread.is_alive():
            self._checker_thread.join(timeout=2.0)
