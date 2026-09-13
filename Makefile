.PHONY: test lint typecheck runtime-smoke check infra-check up down

test:
	cd apps/api && uv run python -m pytest

lint:
	cd apps/api && uv run ruff check src tests

typecheck:
	cd apps/api && uv run mypy src

runtime-smoke:
	cd apps/api && DATABASE_URL=postgresql+psycopg://pci:pci@postgres:5432/pci REDIS_URL=redis://redis:6379/0 OBJECT_STORAGE_ENDPOINT=http://minio:9000 OBJECT_STORAGE_BUCKET=pci-objects uv run --no-dev --frozen python -c "import pci.worker"

infra-check:
	docker compose -f infra/compose.yaml config --quiet

check: test lint typecheck runtime-smoke infra-check

up:
	docker compose -f infra/compose.yaml up --build

down:
	docker compose -f infra/compose.yaml down
