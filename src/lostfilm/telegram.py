"""Telegram bot integration for notifications."""

import html
import logging
import os
import re
import urllib.parse
import uuid
from typing import Any, Dict, Optional, Tuple

import requests

from lostfilm.models import Episode

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    """Normalize show name for matching."""
    return re.sub(r"[\W_]+", "", name).lower().strip()


def _extract_series_names(title: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract Russian and English show names from an episode title.
    Example: "Я тебя отыщу (I Will Find You). Эпизод четвёртый (S01E04)"
             -> ("Я тебя отыщу", "I Will Find You")
    """
    match = re.match(r"^(.*?)\s*\(([^)]+)\)", title)
    if match:
        russian_name = match.group(1).strip()
        english_name = match.group(2).strip()
        return russian_name, english_name
    return None, None


class TelegramNotifier:
    """Sends notifications to Telegram via Bot API."""

    def __init__(
        self,
        bot_token: Optional[str],
        chat_id: Optional[str],
        pending_downloads: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the Telegram notifier.

        If ``bot_token`` is provided but ``chat_id`` is not, the notifier will
        attempt to resolve the chat ID automatically by calling ``getUpdates``
        on the Bot API.  This requires that at least one message has been sent
        to the bot beforehand (e.g. send /start in the chat).

        Args:
            bot_token: The Telegram bot token.
            chat_id: The chat ID to send notifications to.  Pass ``None`` to
                     let the notifier discover it automatically.
            pending_downloads: Shared dict mapping short UUIDs to torrent URLs.
                               When provided, episode notifications will include
                               inline "Send to Deluge" buttons.
        """

        # Fall back to environment variables if not provided explicitly.
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or None
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID") or None

        # Shared dict populated here, consumed by the bot callback handler.
        self.pending_downloads: Dict[str, str] = pending_downloads if pending_downloads is not None else {}

        if self.bot_token and not self.chat_id:
            logger.info(
                "TELEGRAM_CHAT_ID not set — attempting to discover it via getUpdates…"
            )
            self.chat_id = self.fetch_chat_id()

        if self.bot_token:
            self._verify_bot()

        if self.is_enabled():
            logger.info(
                "Telegram notifier initialized and enabled (chat_id=%s)", self.chat_id
            )
        else:
            logger.warning("Telegram notifier disabled (missing token or chat_id)")

    def _verify_bot(self) -> None:
        """Verify the bot token and log bot identity."""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            if data.get("ok"):
                bot_name = data["result"].get("username")
                logger.info("Connected to Telegram Bot: @%s", bot_name)
        except Exception as e:
            logger.warning("Could not verify Telegram bot token: %s", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Check if Telegram notifications are enabled."""
        return bool(self.bot_token and self.chat_id)

    def fetch_chat_id(self) -> Optional[str]:
        """
        Discover the chat ID by polling ``getUpdates``.

        The bot must have received at least one message (e.g. ``/start``)
        from the target chat before this is called; otherwise Telegram returns
        an empty update list and ``None`` is returned.

        Returns:
            The chat ID as a string, or ``None`` if it could not be determined.
        """
        if not self.bot_token:
            logger.warning("Cannot fetch chat_id: bot_token is not set.")
            return None

        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            updates = data.get("result", [])
            if not updates:
                logger.warning(
                    "getUpdates returned no messages. "
                    "Send a message (e.g. /start) to the bot first, then retry."
                )
                return None

            # Use the most recent update that has a message or channel_post.
            for update in reversed(updates):
                message = update.get("message") or update.get("channel_post")
                if message:
                    chat_id = str(message["chat"]["id"])
                    logger.info("Auto-discovered TELEGRAM_CHAT_ID=%s", chat_id)
                    return chat_id

            logger.warning(
                "getUpdates contained updates but none had a recognisable message."
            )
            return None

        except requests.RequestException as e:
            logger.error("Failed to fetch chat_id via getUpdates: %s", e)
            return None

    def _find_show_info(self, title: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Search lostfilm.tv for the series poster image URL and show page URL.

        Args:
            title: The episode title.

        Returns:
            Tuple of (poster_url, show_page_url), either may be None if not found.
        """
        russian_name, english_name = _extract_series_names(title)
        if not english_name:
            return None, None

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        # Try searching for the English name first, then Russian as fallback
        for query_name in [english_name, russian_name]:
            if not query_name:
                continue
            query = urllib.parse.quote(query_name)
            url = f"https://www.lostfilm.tv/search/?q={query}"
            try:
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    pattern = re.compile(
                        r'<div class="row-search">.*?'
                        r'href="(?P<href>/series/[^"]+)".*?'
                        r'<img src="(?P<img_src>[^"]+)" class="thumb".*?'
                        r'<div class="name-ru">(?P<name_ru>[^<]+)</div>.*?'
                        r'<div class="name-en">(?P<name_en>[^<]+)</div>',
                        re.DOTALL,
                    )
                    matches = [m.groupdict() for m in pattern.finditer(response.text)]

                    target_en = _normalize_name(english_name)
                    target_ru = _normalize_name(russian_name) if russian_name else ""

                    for m in matches:
                        m_en = _normalize_name(m["name_en"])
                        m_ru = _normalize_name(m["name_ru"])
                        if (target_en and m_en == target_en) or (
                            target_ru and m_ru == target_ru
                        ):
                            img_src = m["img_src"]
                            if img_src.startswith("//"):
                                img_src = "https:" + img_src
                            elif img_src.startswith("/"):
                                img_src = "https://www.lostfilm.tv" + img_src

                            show_page_url = "https://www.lostfilm.tv" + m["href"]

                            # Try to use poster.jpg instead of image.jpg for higher-res poster
                            if "image.jpg" in img_src:
                                poster_src = img_src.replace("image.jpg", "poster.jpg")
                                try:
                                    r_head = requests.head(
                                        poster_src, headers=headers, timeout=2
                                    )
                                    if r_head.status_code == 200:
                                        return poster_src, show_page_url
                                except Exception:
                                    pass

                            return img_src, show_page_url
            except Exception as e:
                logger.debug("Failed to search show info for %s: %s", title, e)

        return None, None

    def _build_inline_keyboard(self, episode: Episode) -> Optional[Dict[str, Any]]:
        """
        Build a Telegram InlineKeyboardMarkup for Deluge download buttons.

        Each button registers a short UUID → torrent_url entry in
        ``self.pending_downloads`` so the callback data stays under Telegram's
        64-byte limit.

        Returns the ``reply_markup`` dict, or ``None`` if there are no qualities
        or no pending_downloads dict is configured.
        """
        if not episode.qualities:
            return None

        buttons = []
        for quality, torrent_url in sorted(episode.qualities.items()):
            # Register a short key so callback_data stays ≤ 64 bytes
            short_id = uuid.uuid4().hex[:8]
            self.pending_downloads[short_id] = torrent_url
            callback_data = f"dl:{short_id}"  # 11 bytes
            buttons.append(
                [{"text": f"⬇ {quality} → Deluge", "callback_data": callback_data}]
            )

        return {"inline_keyboard": buttons}

    def send_episode_notification(self, episode: Episode) -> bool:
        """
        Send a notification for a new episode.

        Args:
            episode: The episode details to send.

        Returns:
            True if the notification was sent successfully (or if disabled), False otherwise.
        """
        if not self.is_enabled():
            return True

        # Use HTML for more robust formatting and to avoid manual markdown escaping.
        title = html.escape(episode.title)
        # LostFilm links usually don't need escaping but better safe.
        link = html.escape(episode.link)

        # Using the new tg-time entity from Bot API 9.5 (March 2026)
        timestamp = int(episode.pub_date.timestamp())
        formatted_date = episode.pub_date.strftime("%Y-%m-%d %H:%M")

        quality_links = []
        # Sort qualities in a predictable order if possible, or just iterate
        for q, url in sorted(episode.qualities.items()):
            quality_links.append(
                f'• <a href="{html.escape(url)}">Download {html.escape(q)}</a>'
            )

        # Try to search for poster image URL and show page URL
        poster_url, show_page_url = self._find_show_info(episode.title)
        lostfilm_link = html.escape(show_page_url) if show_page_url else link

        links_block = "\n".join(quality_links)

        # Build inline keyboard if Deluge integration is active
        reply_markup = self._build_inline_keyboard(episode)

        message = (
            f"🎬 <b>New Episode Available</b>\n\n"
            f"<b>{title}</b>\n"
            f'Released: <tg-time unix="{timestamp}" format="Dt">at {formatted_date}</tg-time>\n\n'
            f"<b>Downloads:</b>\n{links_block}\n\n"
            f'<a href="{lostfilm_link}">View on LostFilm</a>'
        )

        # Telegram's Bot API requires chat_id to be an integer for private chats.
        chat_id: int | str = self.chat_id  # type: ignore[assignment]
        if str(self.chat_id).lstrip("-").isdigit():
            chat_id = int(self.chat_id)

        import json as _json
        reply_markup_json = _json.dumps(reply_markup) if reply_markup else None

        # If a poster URL is found, try to send it via sendPhoto
        if poster_url:
            photo_url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
            photo_data: Dict[str, Any] = {
                "chat_id": chat_id,
                "photo": poster_url,
                "caption": message,
                "parse_mode": "HTML",
            }
            if reply_markup_json:
                photo_data["reply_markup"] = reply_markup_json
            try:
                response = requests.post(photo_url, data=photo_data, timeout=10)
                response.raise_for_status()
                logger.debug(f"Successfully sent photo notification for {episode.title}")
                return True
            except requests.RequestException as photo_err:
                logger.warning(
                    "Failed to send Telegram notification with photo: %s. "
                    "Falling back to text message.",
                    photo_err,
                )

        # Fallback to sendMessage (text-only)
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        data: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "link_preview_options": '{"is_disabled": true}',
        }
        if reply_markup_json:
            data["reply_markup"] = reply_markup_json

        try:
            # Using form-data (data=) instead of JSON for maximum compatibility with all environments.
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            logger.debug(f"Successfully sent text notification for {episode.title}")
            return True
        except requests.RequestException as e:
            body = ""
            if e.response is not None:
                body = e.response.text

            error_desc = ""
            try:
                if body:
                    resp_json = e.response.json() if e.response else {}
                    error_desc = resp_json.get("description", "")
            except Exception:
                error_desc = body

            if "chat not found" in error_desc.lower():
                logger.error(
                    "Telegram Error: Chat not found (%s). "
                    "You must first send a message to the bot (@danger_ua_bot) to start a chat.",
                    self.chat_id,
                )
            else:
                logger.error(
                    "Failed to send Telegram notification: %s %s", e, error_desc
                )
            return False
