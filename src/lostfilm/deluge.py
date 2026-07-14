"""Deluge Web Client integration for adding torrents automatically."""

import logging
import os
from typing import Optional

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
        url: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.url = (url or os.getenv("DELUGE_URL", "")).rstrip("/")
        self.password = password or os.getenv("DELUGE_PASS", "")

        if not self.url:
            raise ValueError("DELUGE_URL is not set.")

    def is_configured(self) -> bool:
        """Return True if both URL and password are provided."""
        return bool(self.url and self.password is not None)

    def add_torrent_url(
        self,
        torrent_url: str,
        lf_cookies: Optional[dict] = None,
    ) -> bool:
        """
        Download a .torrent file from *torrent_url* and add it to Deluge.

        Args:
            torrent_url: The LostFilm download URL for the .torrent file.
            lf_cookies: Optional dict of LostFilm session cookies
                        (``{"uid": ..., "usess": ...}``) used to authenticate
                        the download request.

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
            return False

        # --- 2. Upload to Deluge WebUI ---
        try:
            import tempfile
            import os as _os
            from deluge_web_client import DelugeWebClient, TorrentOptions  # type: ignore[import-untyped]

            torrent_options = TorrentOptions(
                label="serials"
            )

            # upload_torrent() requires a file path, not raw bytes —
            # write to a temp file then clean up.
            with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tmp:
                tmp.write(torrent_bytes)
                tmp_path = tmp.name

            try:
                client = DelugeWebClient(url=self.url, password=self.password)
                client.login()
                result = client.upload_torrent(
                    torrent_path=tmp_path,
                    torrent_options=torrent_options,
                )
                client.close_session()
            finally:
                _os.unlink(tmp_path)

            if result and result.result:
                logger.info(
                    "Torrent successfully added to Deluge: %s", torrent_url
                )
                return True
            else:
                logger.warning(
                    "Deluge responded but result was falsy: %s", result
                )
                return False

        except Exception as e:
            logger.error("Failed to add torrent to Deluge: %s", e)
            return False
