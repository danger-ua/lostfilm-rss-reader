"""Telegram bot integration for notifications."""

import html
import logging
import os
from typing import Any, Dict, Optional

import requests

from lostfilm.models import Episode

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends notifications to Telegram via Bot API."""

    def __init__(self, bot_token: Optional[str], chat_id: Optional[str]):
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
        """

        # Fall back to environment variables if not provided explicitly.
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or None
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID") or None

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
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
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

        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdate"
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

        links_block = "\n".join(quality_links)

        message = (
            f"🎬 <b>New Episode Available</b>\n\n"
            f"<b>{title}</b>\n"
            f'Released: <tg-time unix="{timestamp}" format="Dt">at {formatted_date}</tg-time>\n\n'
            f"<b>Downloads:</b>\n{links_block}\n\n"
            f'<a href="{link}">View on LostFilm</a>'
        )

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        # Telegram's Bot API requires chat_id to be an integer for private chats.
        chat_id: int | str = self.chat_id  # type: ignore[assignment]
        if str(self.chat_id).lstrip("-").isdigit():
            chat_id = int(self.chat_id)

        data: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "link_preview_options": '{"is_disabled": true}',
        }

        try:
            # Using form-data (data=) instead of JSON for maximum compatibility with all environments.
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            logger.debug(f"Successfully sent notification for {episode.title}")
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
