"""
Root pytest configuration.

Loads variables from the project's .env file into the process environment
before any test is collected or run, so integration tests (e.g. the live
Telegram test) can pick up real credentials without manual env-var exports.

Variables already present in the environment take precedence (override=False),
so CI can still inject its own secrets without being overridden by the file.
"""

from dotenv import load_dotenv

# Load .env from the project root (same directory as this conftest.py).
# override=False means existing env vars win — safe for CI.
load_dotenv(dotenv_path=".env", override=False)
