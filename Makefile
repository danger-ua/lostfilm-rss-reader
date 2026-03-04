.PHONY: help install sync test lint format typecheck run clean

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
	@echo "  clean      Remove __pycache__ and .pytest_cache directories"

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
