set shell := ["bash", "-euo", "pipefail", "-c"]
default:
    @just --list
check: fmt-check lint test
ci: check
    scripts/run-gitleaks.sh git --no-banner --redact .
test:
    uv run --locked pytest
fmt:
    uv run --locked ruff format .
    uv run --locked ruff check --fix .
fmt-check:
    uv run --locked ruff format --check .
lint:
    uv run --locked ruff check .
setup:
    uv sync --locked
    npm ci
    lefthook install
build:
    uv build
