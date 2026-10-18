.PHONY: test lint typecheck web-test web-build e2e runtime-smoke check infra-check backup-restore-smoke up down

test:
	cd apps/api && uv run python -m pytest

lint:
	cd apps/api && uv run ruff check src tests

typecheck:
	cd apps/api && uv run mypy src

web-test:
	cd apps/web && npm test && npm run typecheck

web-build:
	cd apps/web && npm run build

e2e:
	cd apps/web && npm run test:e2e

runtime-smoke:
	cd apps/api && DATABASE_URL=postgresql+psycopg://pci:pci@postgres:5432/pci REDIS_URL=redis://redis:6379/0 OBJECT_STORAGE_ENDPOINT=http://minio:9000 OBJECT_STORAGE_BUCKET=pci-objects uv run --no-dev --frozen python -c "import pci.worker"

infra-check:
	docker compose -f infra/compose.yaml config --quiet

check: test lint typecheck web-test web-build runtime-smoke infra-check

backup-restore-smoke:
	./scripts/verify-backup-restore.sh

up:
	docker compose -f infra/compose.yaml up --build

down:
	docker compose -f infra/compose.yaml down
