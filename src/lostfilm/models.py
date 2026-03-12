"""Data models for LostFilm RSS feed items."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict


@dataclass
class Episode:
    """Represents an episode/release from the LostFilm RSS feed."""

    id: str
    title: str
    link: str
    pub_date: datetime
    qualities: Dict[str, str]

    def to_dict(self) -> dict:
        """Convert episode to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "link": self.link,
            "pub_date": self.pub_date.isoformat(),
            "qualities": self.qualities,
        }
