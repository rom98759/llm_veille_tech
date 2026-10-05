install:
	pip install -r requirements.lock && pip install -e '.[dev]' && pre-commit install

lint:
	ruff check . && ruff format --check .

format:
	ruff check --fix . && ruff format .

test:
	pytest

check: lint test

feeds:
	veille check-feeds

.PHONY: install lint format test check feeds
