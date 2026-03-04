"""Scheduler for periodic LossFilm RSS feed checks."""

import time
import logging

from lostfilm.client import LostFilmClient
from lostfilm.storage import Storage

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Scheduler:
    """Periodically checks the RSS feed and stores new items."""

    def __init__(
        self, client: LostFilmClient, storage: Storage, interval_seconds: int = 3600
    ):
        """
        Initialize the scheduler.

        Args:
            client: LostFilmClient instance.
            storage: Storage instance.
            interval_seconds: Check interval in seconds.
        """
        self.client = client
        self.storage = storage
        self.interval_seconds = interval_seconds
        self.running = False

    def check_once(self):
        """Perform a single check of the RSS feed."""
        logger.info("Checking favorites RSS feed...")
        try:
            episodes = self.client.fetch_favorites_feed()
            new_count = self.storage.store_episodes(episodes)
            logger.info(
                f"Check complete. Found {len(episodes)} episodes, stored {new_count} new ones."
            )
        except Exception as e:
            logger.error(f"Error during RSS check: {e}")

    def start(self):
        """Start the periodic check loop."""
        self.running = True
        logger.info(f"Starting scheduler with {self.interval_seconds}s interval.")

        # Initial check
        self.check_once()

        try:
            while self.running:
                logger.info(f"Sleeping for {self.interval_seconds} seconds...")
                time.sleep(self.interval_seconds)
                self.check_once()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """Stop the periodic check loop."""
        logger.info("Stopping scheduler...")
        self.running = False
