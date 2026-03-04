"""Data models for LostFilm RSS feed items."""

from dataclasses import dataclass
from datetime import datetime
from typing import Union


@dataclass
class Episode:
    """Represents an episode/release from the LostFilm RSS feed."""

    id: Union[str, int]
    title: str
    link: str
    pub_date: datetime

    @property
    def download_url(self) -> str:
        """Generate the download URL for this episode."""
        return f"https://n.tracktor.site/rssdownloader.php?id={self.id}"

    def to_dict(self) -> dict:
        """Convert episode to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "title": self.title,
            "link": self.link,
            "pub_date": self.pub_date.isoformat(),
            "download_url": self.download_url,
        }
