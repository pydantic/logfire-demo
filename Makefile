.DEFAULT_GOAL := all

.PHONY: install
install:
	uv sync --frozen
	pre-commit install

.PHONY: build-docker
build-docker:
	docker compose build

.PHONY: up
up:
	docker compose up --build

.PHONY: format
format:
	uv run ruff check --fix-only src
	uv run ruff format src

.PHONY: lint
lint:
	uv run ruff check src
	uv run ruff format --check src
