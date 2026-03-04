"""SQLite storage for LostFilm RSS items."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from lostfilm.models import Episode


class Storage:
    """Handles SQLite database operations for storing episodes."""

    def __init__(self, db_path: str = "lostfilm.db"):
        """
        Initialize the storage.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create the episodes table if it doesn't exist."""
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    link TEXT NOT NULL,
                    pub_date TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def store_episode(self, episode: Episode) -> bool:
        """
        Store a single episode in the database.

        Returns:
            True if the episode was newly added, False if it already existed.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Check if exists
            cursor.execute("SELECT 1 FROM episodes WHERE id = ?", (str(episode.id),))
            if cursor.fetchone():
                return False

            cursor.execute(
                """
                INSERT INTO episodes (id, title, link, pub_date, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(episode.id),
                    episode.title,
                    episode.link,
                    episode.pub_date.isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return True

    def store_episodes(self, episodes: List[Episode]) -> int:
        """
        Store a list of episodes.

        Returns:
            Number of newly added episodes.
        """
        count = 0
        for ep in episodes:
            if self.store_episode(ep):
                count += 1
        return count

    def get_episodes(self, limit: int = 50) -> List[Episode]:
        """
        Retrieve stored episodes from the database.

        Args:
            limit: Maximum number of episodes to return.

        Returns:
            List of Episode objects sorted by publication date (newest first).
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, link, pub_date FROM episodes ORDER BY pub_date DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()

            episodes = []
            for row in rows:
                episodes.append(
                    Episode(
                        id=row[0],
                        title=row[1],
                        link=row[2],
                        pub_date=datetime.fromisoformat(row[3]),
                    )
                )
            return episodes

    def get_episode_by_id(self, item_id: str) -> Optional[Episode]:
        """Find an episode by its ID in the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, link, pub_date FROM episodes WHERE id = ?",
                (str(item_id),),
            )
            row = cursor.fetchone()
            if row:
                return Episode(
                    id=row[0],
                    title=row[1],
                    link=row[2],
                    pub_date=datetime.fromisoformat(row[3]),
                )
            return None
