# LostFilm.tv RSS Reader

A Python CLI application for monitoring LostFilm.tv RSS feeds, accessing user-specific favorite lists, and resolving direct download links for `.torrent` files.

## Features

- 🔐 **Session-based Authentication** - Uses LostFilm.tv session tokens (`uid` and `usess`)
- 📡 **RSS Feed Monitoring** - Fetch global and favorites-only feeds
- 🔗 **Download Link Resolution** - Generate direct download URLs for torrent files
- ⏱️ **Rate Limiting** - Built-in 15-minute rate limiting to prevent IP blocking
- 🎨 **Beautiful CLI** - Rich formatted tables or JSON output
- 🔒 **Secure Credential Storage** - Environment variable support

## Requirements

- Python 3.12 or higher
- LostFilm.tv account credentials (`uid` and `usess` tokens)

## Installation

1. Clone or download this repository:

```bash
cd lostfilm-rss-reader
```

2. Install dependencies using `uv`:

```bash
uv pip install -e .
```

Or using pip:

```bash
pip install -e .
```

## Configuration

### Getting Your Credentials

1. Log in to [LostFilm.tv](http://lostfilm.tv) in your web browser
2. Open browser developer tools (F12)
3. Go to the Application/Storage tab → Cookies
4. Find the `uid` and `usess` cookies
5. Copy their values

### Setting Up Credentials

You can provide credentials in two ways:

#### Option 1: Environment Variables (Recommended)

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```
LOSTFILM_UID=your_user_id_here
LOSTFILM_USESS=your_session_token_here
```

#### Option 2: Command Line Arguments

Pass credentials directly via CLI flags (less secure):

```bash
lostfilm --uid YOUR_UID --usess YOUR_USESS list-favorites
```

## Usage

### List Favorite Episodes

Display the 10 latest episodes from your favorites list:

```bash
lostfilm list-favorites
```

Output in JSON format:

```bash
lostfilm list-favorites --json
```

Limit the number of results:

```bash
lostfilm list-favorites --limit 5
```

### Get Download URL

Get the direct download URL for a specific episode:

```bash
lostfilm get-download-url 12345
```

This will output:
```
http://tracktor.in/rssdownloader.php?id=12345
```

## Error Handling

The application handles various error conditions:

- **AuthenticationError**: Session tokens expired (HTTP 403)
- **ServerError**: Server temporarily unavailable (HTTP 503)
- **RateLimitError**: Requests made too frequently
- **ParseError**: RSS feed parsing failed

## Security Notes

- Never share your `usess` token - it provides full access to your account
- The `usess` token is never logged or printed to stdout
- Store credentials in `.env` file (which is gitignored) rather than hardcoding

## Rate Limiting

The application enforces a 15-minute minimum interval between requests to the same endpoint to prevent IP blocking. If you exceed this limit, you'll receive a `RateLimitError` with instructions on how long to wait.

## License

This project is provided as-is for personal use.
