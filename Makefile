.PHONY: help install test lint typecheck format clean run

help:
	@echo "Available targets:"
	@echo "  install    Install dependencies using uv"
	@echo "  test       Run tests using pytest"
	@echo "  lint       Run linter (ruff)"
	@echo "  typecheck  Run type checker (mypy)"
	@echo "  format     Run code formatter (ruff)"
	@echo "  coverage   Run tests with coverage report"
	@echo "  clean      Remove temporary files"
	@echo "  run        Run the gcpath tool"

install:
	uv sync

test:
	uv run pytest

coverage:
	uv run pytest --cov=src --cov-report=term-missing

lint:
	uv run ruff check .

typecheck:
	uv run mypy .

format:
	uv run ruff format .
	uv run ruff check . --fix

clean:
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +

run:
	uv run gcpath $(filter-out $@,$(MAKECMDGOALS))

# This allows passing arguments to the run target
%:
	@:
