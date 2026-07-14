"""Telegram bot polling loop for handling inline-keyboard download callbacks."""

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Dict, Optional

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

if TYPE_CHECKING:
    from lostfilm.deluge import DelugeClient

logger = logging.getLogger(__name__)


class DownloadBot:
    """
    Runs a python-telegram-bot ``Application`` in a daemon thread.

    It listens for ``callback_query`` updates whose data starts with ``dl:``.
    On receipt it:
      1. Looks up the torrent URL from the shared *pending_downloads* dict.
      2. Downloads the .torrent and adds it to Deluge via :class:`DelugeClient`.
      3. Answers the callback query with a ✅ / ❌ alert.

    NOTE: ``Application.run_polling()`` installs OS signal handlers and must
    only be called from the main thread.  This class uses the lower-level
    async API (``initialize`` / ``start`` / ``updater.start_polling``) so it
    can safely run inside a daemon thread.
    """

    CALLBACK_PREFIX = "dl:"

    def __init__(
        self,
        bot_token: str,
        deluge_client: "DelugeClient",
        pending_downloads: Dict[str, str],
        lf_cookies: Optional[Dict[str, str]] = None,
    ) -> None:
        self.bot_token = bot_token
        self.deluge = deluge_client
        self.pending = pending_downloads
        self.lf_cookies = lf_cookies or {}
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[asyncio.Event] = None

    # ------------------------------------------------------------------
    # Callback handler
    # ------------------------------------------------------------------

    async def _handle_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None:
            return

        data: str = query.data or ""
        if not data.startswith(self.CALLBACK_PREFIX):
            return

        uuid = data[len(self.CALLBACK_PREFIX):]

        # Acknowledge immediately so Telegram removes the loading spinner
        await query.answer("⏳ Adding to Deluge…")

        torrent_url = self.pending.pop(uuid, None)
        if not torrent_url:
            logger.warning("Callback for unknown/expired uuid=%s", uuid)
            await query.answer(
                "❌ Link expired or already used.", show_alert=True
            )
            return

        logger.info(
            "Received download callback uuid=%s url=%s", uuid, torrent_url
        )

        # Run the blocking Deluge call off the event loop thread
        ok = await asyncio.to_thread(
            self.deluge.add_torrent_url, torrent_url, self.lf_cookies
        )

        status_text = "✅ Added to Deluge!" if ok else "❌ Failed to add to Deluge."
        await query.answer(status_text, show_alert=True)

        # Reply to the notification message with a status line
        if query.message:
            try:
                await query.message.reply_text(status_text)
            except Exception as e:
                logger.debug("Could not send status reply: %s", e)

    # ------------------------------------------------------------------
    # Async entrypoint — safe to run inside any thread's event loop
    # ------------------------------------------------------------------

    async def _run_async(self) -> None:
        """
        Build the Application, start polling, and block until the daemon
        thread is killed by process exit.

        Uses the lower-level async API so no signal handlers are installed
        (those are restricted to the main thread in CPython).
        """
        self._stop_event = asyncio.Event()

        app = Application.builder().token(self.bot_token).build()
        app.add_handler(CallbackQueryHandler(self._handle_callback))

        await app.initialize()
        await app.start()
        logger.info("Telegram bot polling started (Deluge integration active).")

        assert app.updater is not None  # always set when using default builder
        await app.updater.start_polling(
            allowed_updates=["callback_query"],
            drop_pending_updates=True,
        )

        # Block here until process exits (daemon thread); stop_event lets
        # a graceful shutdown path signal us cleanly if ever needed.
        await self._stop_event.wait()

        # Graceful teardown
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def _thread_target(self) -> None:
        """Entry point for the daemon thread — owns its own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async())
        except Exception as e:
            logger.error("Bot polling thread crashed: %s", e, exc_info=True)
        finally:
            loop.close()

    def start(self) -> None:
        """Start the bot in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Bot thread is already running.")
            return

        self._thread = threading.Thread(
            target=self._thread_target,
            name="telegram-bot-polling",
            daemon=True,
        )
        self._thread.start()
        logger.info("Telegram bot polling thread started.")

    def stop(self) -> None:
        """Signal the polling loop to shut down gracefully."""
        if self._stop_event is not None:
            # Schedule set() on the loop that owns the event
            if self._thread and self._thread.is_alive():
                loop = asyncio.get_event_loop()
                loop.call_soon_threadsafe(self._stop_event.set)
