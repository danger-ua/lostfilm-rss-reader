#!/usr/bin/env python3
"""CLI interface for LostFilm.tv RSS reader."""

import argparse
import json
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from lostfilm.client import LostFilmClient
from lostfilm.exceptions import (
    AuthenticationError,
    LostFilmError,
    ParseError,
    RateLimitError,
    ServerError,
)
from lostfilm.scheduler import Scheduler
from lostfilm.storage import Storage
from lostfilm.telegram import TelegramNotifier

# Load environment variables from .env file if it exists
load_dotenv()

console = Console()
err_console = Console(stderr=True)


def print_episodes_table(episodes, limit: int = 10):
    """Print episodes in a formatted table."""
    table = Table(
        title="Latest Favorite Episodes", show_header=True, header_style="bold magenta"
    )
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="green")
    table.add_column("Date", style="yellow")
    table.add_column("Qualities", style="blue")

    for episode in episodes[:limit]:
        qualities_str = ", ".join(episode.qualities.keys()) if hasattr(episode, 'qualities') else ""
        table.add_row(
            str(episode.id),
            episode.title,
            episode.pub_date.strftime("%Y-%m-%d %H:%M"),
            qualities_str,
        )

    console.print(table)


def print_episodes_json(episodes, limit: int = 10):
    """Print episodes in JSON format."""
    episodes_data = [episode.to_dict() for episode in episodes[:limit]]
    print(json.dumps(episodes_data, indent=2, ensure_ascii=False))


def list_favorites(
    uid: Optional[str], usess: Optional[str], json_output: bool, limit: int
):
    """List favorite episodes."""
    try:
        client = LostFilmClient(uid=uid, usess=usess)
        episodes = client.fetch_favorites_feed()

        # Sort by publication date (newest first)
        episodes.sort(key=lambda x: x.pub_date, reverse=True)

        if json_output:
            print_episodes_json(episodes, limit)
        else:
            print_episodes_table(episodes, limit)

    except AuthenticationError as e:
        err_console.print(f"[red]Authentication Error:[/red] {e.message}")
        sys.exit(1)
    except ServerError as e:
        err_console.print(f"[red]Server Error:[/red] {e.message}")
        sys.exit(1)
    except RateLimitError as e:
        err_console.print(f"[yellow]Rate Limit:[/yellow] {e.message}")
        sys.exit(1)
    except ParseError as e:
        err_console.print(f"[red]Parse Error:[/red] {e.message}")
        sys.exit(1)
    except LostFilmError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        err_console.print(f"[red]Unexpected Error:[/red] {e}")
        sys.exit(1)


def get_download_url(item_id: str, uid: Optional[str], usess: Optional[str]):
    """Get download URL for a specific item ID."""
    try:
        client = LostFilmClient(uid=uid, usess=usess)
        episode = client.get_episode_by_id(item_id)
        if episode and hasattr(episode, 'qualities') and episode.qualities:
            for q, dl_url in episode.qualities.items():
                print(f"{q}: {dl_url}")
        else:
            url = client.get_download_url(item_id)
            print(url)
    except LostFilmError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        err_console.print(f"[red]Unexpected Error:[/red] {e}")
        sys.exit(1)


def check_auth(uid: Optional[str], usess: Optional[str]):
    """Check if the provided credentials are valid."""
    try:
        client = LostFilmClient(uid=uid, usess=usess)
        with console.status("[bold blue]Checking authentication..."):
            is_valid = client.validate_credentials()

        if is_valid:
            console.print("[bold green]✓ Authentication successful![/bold green]")
            console.print(f"UID: [cyan]{client.uid}[/cyan]")
            console.print(f"USESS: [cyan]{client.usess}[/cyan]")
        else:
            err_console.print("[bold red]✗ Authentication failed![/bold red]")
            err_console.print(
                "Please check your LOSTFILM_UID and LOSTFILM_USESS environment variables."
            )
            sys.exit(1)
    except LostFilmError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        err_console.print(f"[red]Unexpected Error:[/red] {e}")
        sys.exit(1)


def sanitize_filename(filename: str) -> str:
    """Sanitize filename by removing or replacing invalid characters."""
    import re

    # Replace invalid characters with underscore
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", filename)
    # Also replace spaces with underscores for better compatibility
    sanitized = sanitized.replace(" ", "_").replace("(", "").replace(")", "")
    return sanitized


def download(
    item_id: str, output_path: Optional[str], uid: Optional[str], usess: Optional[str]
):
    """Download torrent file for a specific item ID."""
    try:
        client = LostFilmClient(uid=uid, usess=usess)

        # Default filename based on title if possible
        episode = client.get_episode_by_id(item_id)
        
        download_url = None
        if episode:
            if not output_path:
                output_path = sanitize_filename(episode.title) + ".torrent"
            # Pick best available
            for q in ["1080p", "720p", "SD", "MP4"]:
                if q in episode.qualities:
                    download_url = episode.qualities[q]
                    break
            if not download_url and episode.qualities:
                download_url = list(episode.qualities.values())[0]
        else:
            if not output_path:
                output_path = f"{item_id}.torrent"
            download_url = client.get_download_url(item_id)

        if not download_url:
            raise LostFilmError("No download URL found")

        # Reuse client logic to download raw
        content = client._make_request(download_url, "download_torrent")

        with open(output_path, "wb") as f:
            f.write(content)

        console.print(
            f"[green]Successfully downloaded torrent to {output_path}[/green]"
        )

    except LostFilmError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        err_console.print(f"[red]Unexpected Error:[/red] {e}")
        sys.exit(1)


def start_scheduler(
    uid: Optional[str],
    usess: Optional[str],
    db_path: str,
    interval: int,
):
    """Start the periodic RSS check scheduler."""
    try:
        client = LostFilmClient(uid=uid, usess=usess)
        storage = Storage(db_path=db_path)

        # Initialize Telegram Notifier
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)

        scheduler = Scheduler(
            client, storage, interval_seconds=interval, notifier=notifier
        )

        console.print("[bold blue]Starting scheduler...[/bold blue]")
        console.print(f"Database: [cyan]{db_path}[/cyan]")
        console.print(f"Interval: [cyan]{interval}s[/cyan]")
        if notifier.is_enabled():
            console.print(
                "[bold magenta]Telegram Notifications:[/bold magenta] [green]Enabled[/green]"
            )
        else:
            console.print(
                "[bold magenta]Telegram Notifications:[/bold magenta] [yellow]Disabled[/yellow]"
            )

        scheduler.start()
    except Exception as e:
        err_console.print(f"[red]Error starting scheduler:[/red] {e}")
        sys.exit(1)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="LostFilm.tv RSS feed reader and download link resolver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global options
    parser.add_argument(
        "--uid",
        type=str,
        default=None,
        help="User ID token (overrides LOSTFILM_UID environment variable)",
    )
    parser.add_argument(
        "--usess",
        type=str,
        default=None,
        help="Session token (overrides LOSTFILM_USESS environment variable)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list-favorites command
    list_parser = subparsers.add_parser(
        "list-favorites", help="List latest favorite episodes"
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of episodes to display (default: 10)",
    )

    # get-download-url command
    download_parser = subparsers.add_parser(
        "get-download-url", help="Get download URL for a specific item ID"
    )
    download_parser.add_argument("item_id", type=str, help="Numeric item ID")
    # download command
    download_parser = subparsers.add_parser(
        "download", help="Download torrent file for a specific item ID"
    )
    download_parser.add_argument("item_id", type=str, help="Numeric item ID")
    download_parser.add_argument(
        "-o", "--output", type=str, help="Output file path (default: {item_id}.torrent)"
    )

    # check-auth command
    subparsers.add_parser("check-auth", help="Check if UID and USESS tokens are valid")

    # scheduler command
    sched_parser = subparsers.add_parser(
        "scheduler", help="Run periodic RSS check and store new items"
    )
    sched_parser.add_argument(
        "--db",
        type=str,
        default=os.getenv("DB_PATH", "lostfilm.db"),
        help="Path to SQLite database",
    )
    sched_parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("CHECK_INTERVAL_SECONDS", "3600")),
        help="Check interval in seconds",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Get credentials from args or environment
    uid = args.uid or os.getenv("LOSTFILM_UID")
    usess = args.usess or os.getenv("LOSTFILM_USESS")

    if args.command == "list-favorites":
        list_favorites(uid, usess, args.json, args.limit)
    elif args.command == "get-download-url":
        get_download_url(args.item_id, uid, usess)
    elif args.command == "download":
        download(args.item_id, args.output, uid, usess)
    elif args.command == "check-auth":
        check_auth(uid, usess)
    elif args.command == "scheduler":
        start_scheduler(uid, usess, args.db, args.interval)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
