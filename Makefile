.PHONY: setup build run test check

setup:
	uv sync --locked --extra dev
	npm --prefix frontend ci

build:
	npm --prefix frontend run build

run:
	uv run uvicorn gridsense.api:app --host 127.0.0.1 --port 8000

test:
	uv run pytest -q
	npm --prefix frontend test

check:
	uv run ruff check backend tests scripts
	uv run ruff format --check backend tests scripts
	npm --prefix frontend run build
