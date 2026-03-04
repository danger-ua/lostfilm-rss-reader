"""RSS feed parsing logic."""

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Union

from dateutil import parser as date_parser

from lostfilm.exceptions import ParseError
from lostfilm.models import Episode


def parse_rss_feed(xml_content: Union[str, bytes]) -> List[Episode]:
    """
    Parse RSS feed XML content and return a list of Episode objects.

    Args:
        xml_content: Raw XML string or bytes from RSS feed

    Returns:
        List of Episode objects

    Raises:
        ParseError: If the XML cannot be parsed or is malformed
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ParseError(f"Failed to parse XML: {e}") from e

    episodes = []
    namespace = {"": "http://www.w3.org/2005/Atom"}

    # Try RSS 2.0 format first
    items = root.findall(".//item")
    if not items:
        # Try Atom format
        items = root.findall(".//entry", namespace)
        if not items:
            raise ParseError("No items found in RSS feed")

    for item in items:
        try:
            # Extract ID from guid or link
            item_id = None
            guid_elem = item.find("guid")
            if guid_elem is not None:
                item_id = guid_elem.text
            else:
                # Try Atom format id
                id_elem = item.find("id", namespace)
                if id_elem is not None:
                    item_id = id_elem.text
                else:
                    # Fallback to link
                    link_elem = item.find("link")
                    if link_elem is not None:
                        item_id = link_elem.text

            if not item_id:
                continue

            # Extract numeric ID from URL or guid
            numeric_id = _extract_numeric_id(item_id)
            if not numeric_id:
                continue

            # Extract title
            title_elem = item.find("title")
            if title_elem is None:
                title_elem = item.find("title", namespace)
            title = title_elem.text if title_elem is not None else "Unknown"

            # Extract link
            link_elem = item.find("link")
            if link_elem is None:
                # Try Atom format
                link_elem = item.find("link", namespace)
                if link_elem is not None:
                    link = link_elem.get("href", link_elem.text or "")
                else:
                    link = str(item_id)
            else:
                link = link_elem.text or ""

            # Extract publication date
            pub_date_elem = item.find("pubDate")
            if pub_date_elem is None:
                pub_date_elem = item.find("published", namespace)
            if pub_date_elem is None:
                pub_date_elem = item.find("updated", namespace)

            pub_date = datetime.now()
            if pub_date_elem is not None and pub_date_elem.text:
                try:
                    pub_date = date_parser.parse(pub_date_elem.text)
                except (ValueError, TypeError):
                    pass

            episode = Episode(
                id=numeric_id,
                title=title.strip(),
                link=link.strip(),
                pub_date=pub_date,
            )
            episodes.append(episode)

        except Exception:
            # Skip malformed items but continue parsing
            continue

    if not episodes:
        raise ParseError("No valid episodes found in RSS feed")

    return episodes


def _extract_numeric_id(identifier: str) -> str:
    """
    Extract numeric ID from various formats.

    Args:
        identifier: String that may contain a numeric ID (URL, guid, etc.)

    Returns:
        Numeric ID as string, or empty string if not found
    """
    # Try to find numeric ID in the string
    import re

    # Look for patterns like id=123 or /123/ or just a number
    patterns = [
        r"id=(\d+)",
        r"/(\d+)/",
        r"(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, str(identifier))
        if match:
            return match.group(1)

    return ""
