.PHONY: help install sync test lint format typecheck run clean docker-build docker-run test-telegram-live discover-chat-id

# Default target
help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  install    Install all dependencies (prod + dev)"
	@echo "  sync       Sync dependencies from lockfile"
	@echo "  test       Run the test suite"
	@echo "  lint       Lint the codebase with ruff"
	@echo "  format     Format the codebase with ruff"
	@echo "  typecheck  Run static type checking with pyright"
	@echo "  run        Run the CLI application"
	@echo "  clean               Remove __pycache__ and .pytest_cache directories"
	@echo "  docker-build        Build the Docker image"
	@echo "  docker-run          Run the Docker container with .env file"
	@echo "  test-telegram-live  Send a real Telegram test notification (requires .env)"
	@echo "  discover-chat-id    Discover your Telegram chat ID via getUpdates (requires TELEGRAM_BOT_TOKEN)"

install:
	uv sync --all-extras

sync:
	uv sync

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run pyright src/

run:
	uv run python -m lostfilm

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache

docker-build:
	docker build -t lostfilm-rss-reader:latest .

docker-run:
	docker run --rm --env-file .env lostfilm-rss-reader:latest

test-telegram-live:
	set -a && . ./.env && set +a && uv run pytest tests/test_telegram.py::TestTelegramNotifierLive -v

discover-chat-id:
	set -a && . ./.env && set +a && uv run pytest tests/test_telegram.py::TestTelegramDiscoverChatId -v -s
