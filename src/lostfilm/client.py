"""Main client class for LostFilm.tv API interactions."""

import os
import time
from typing import List, Optional, Union

import requests

from lostfilm.exceptions import (
    AuthenticationError,
    LostFilmError,
    ParseError,
    ServerError,
)
from lostfilm.models import Episode
from lostfilm.parser import parse_rss_feed


class LostFilmClient:
    """Client for interacting with LostFilm.tv RSS feeds and download links."""

    RSS_BASE_URL = "http://retre.org/rssdd.xml"
    DOWNLOAD_BASE_URL = "https://n.tracktor.site/rssdownloader.php"
    MIN_REQUEST_INTERVAL = 15 * 60  # 15 minutes in seconds

    def __init__(self, uid: Optional[str] = None, usess: Optional[str] = None):
        """
        Initialize the LostFilm client.

        Args:
            uid: User ID token (optional, will try environment variable)
            usess: Session token (optional, will try environment variable)

        Raises:
            LostFilmError: If credentials are not provided
        """
        self.uid = uid or os.getenv("LOSTFILM_UID")
        self.usess = usess or os.getenv("LOSTFILM_USESS")

        if not self.uid or not self.usess:
            raise LostFilmError(
                "Credentials not provided. Set LOSTFILM_UID and LOSTFILM_USESS "
                "environment variables or pass them to the constructor."
            )

        # Rate limiting: track last request time per endpoint
        self._last_request_time: dict[str, float] = {}

        # Set up session with headers
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Cookie": f"uid={self.uid}; usess={self.usess};",
            }
        )

    def _check_rate_limit(self, endpoint: str) -> None:
        """
        Check if rate limit has been exceeded for the given endpoint.

        Args:
            endpoint: Endpoint identifier (e.g., 'global_feed', 'favorites_feed')

        Raises:
            RateLimitError: If rate limit is exceeded
        """
        from lostfilm.exceptions import RateLimitError

        now = time.time()
        last_time = self._last_request_time.get(endpoint, 0)

        if last_time > 0 and (now - last_time) < self.MIN_REQUEST_INTERVAL:
            wait_time = self.MIN_REQUEST_INTERVAL - (now - last_time)
            raise RateLimitError(
                f"Rate limit exceeded. Please wait {wait_time / 60:.1f} more minutes "
                f"before making another request to {endpoint}."
            )

        self._last_request_time[endpoint] = now

    def _make_request(self, url: str, endpoint: str) -> bytes:
        """
        Make an HTTP GET request with error handling.

        Args:
            url: URL to request
            endpoint: Endpoint identifier for rate limiting

        Returns:
            Response content as bytes

        Raises:
            AuthenticationError: On HTTP 403
            ServerError: On HTTP 503 or other server errors
            LostFilmError: On other errors
        """
        self._check_rate_limit(endpoint)

        try:
            response = self.session.get(url, timeout=30)

            if response.status_code == 403:
                raise AuthenticationError(
                    "Authentication failed. Session tokens may have expired."
                )

            if response.status_code == 503:
                raise ServerError(
                    "Server is temporarily unavailable. Please try again later."
                )

            response.raise_for_status()

            return response.content

        except requests.exceptions.RequestException as e:
            if isinstance(e, (AuthenticationError, ServerError)):
                raise

            # Extract more useful information from RequestException if possible
            msg = str(e)
            if hasattr(e, "response") and e.response is not None:
                msg = f"HTTP {e.response.status_code}: {e.response.reason}"

            raise LostFilmError(f"Network error: {msg}") from e

    def fetch_global_feed(self) -> List[Episode]:
        """
        Fetch and parse the global RSS feed.

        Returns:
            List of Episode objects from the global feed

        Raises:
            AuthenticationError: On authentication failure
            ServerError: On server errors
            ParseError: On RSS parsing errors
        """
        xml_content = self._make_request(self.RSS_BASE_URL, "global_feed")
        return parse_rss_feed(xml_content)

    def fetch_favorites_feed(self) -> List[Episode]:
        """
        Fetch and parse the favorites RSS feed.

        Returns:
            List of Episode objects from the favorites feed

        Raises:
            AuthenticationError: On authentication failure
            ServerError: On server errors
            ParseError: On RSS parsing errors
        """
        url = f"{self.RSS_BASE_URL}?favorites=1"
        xml_content = self._make_request(url, "favorites_feed")
        return parse_rss_feed(xml_content)

    def get_download_url(self, item_id: Union[str, int]) -> str:
        """
        Generate download URL for a specific item ID.

        Args:
            item_id: Numeric ID of the episode/release

        Returns:
            Complete download URL
        """
        return f"{self.DOWNLOAD_BASE_URL}?id={item_id}"

    def download_torrent(self, item_id: Union[str, int]) -> bytes:
        """
        Download the torrent file for a specific item ID.

        Args:
            item_id: Numeric ID of the episode/release

        Returns:
            Binary content of the torrent file

        Raises:
            AuthenticationError: On authentication failure
            ServerError: On server errors
            LostFilmError: On other errors
        """
        url = self.get_download_url(item_id)
        return self._make_request(url, "download_torrent")

    def get_episode_by_id(self, item_id: Union[str, int]) -> Optional[Episode]:
        """
        Find an episode by its ID by searching through favorite and global feeds.

        Args:
            item_id: Numeric ID of the episode/release

        Returns:
            Episode object if found, None otherwise
        """
        str_id = str(item_id)

        # Check favorites first (likely case)
        try:
            favorites = self.fetch_favorites_feed()
            for ep in favorites:
                if str(ep.id) == str_id:
                    return ep
        except LostFilmError:
            pass

        # Check global feed
        try:
            global_feed = self.fetch_global_feed()
            for ep in global_feed:
                if str(ep.id) == str_id:
                    return ep
        except LostFilmError:
            pass

        return None

    def validate_credentials(self) -> bool:
        """
        Validate if the provided credentials (uid, usess) are correct.

        Returns:
            True if credentials are valid, False otherwise.

        Raises:
            ServerError: If the server is down or returns an error.
            LostFilmError: On other network errors.
        """
        try:
            # We try to fetch favorites. If uid/usess are wrong,
            # it should technically return 403 or empty data.
            # Our _make_request handles 403 by raising AuthenticationError.
            self.fetch_favorites_feed()
            return True
        except AuthenticationError:
            return False
        except Exception as e:
            # Re-raise server or parse errors that aren't auth-related
            if isinstance(e, (ServerError, ParseError)):
                raise
            # If it's a LostFilmError but not Auth/Server/Parse, it might be networking
            if isinstance(e, LostFilmError):
                raise
            raise LostFilmError(f"Unexpected error during validation: {e}") from e
