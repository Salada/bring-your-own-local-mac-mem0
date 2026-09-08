.PHONY: all install format format-check sort lint test

all: format sort lint test

install:
	uv sync --extra dev

format:
	uv run --extra dev ruff format .

format-check:
	uv run --extra dev ruff format --check .

sort:
	uv run --extra dev isort .

lint:
	uv run --extra dev ruff check .

test:
	uv run --extra dev pytest tests/
