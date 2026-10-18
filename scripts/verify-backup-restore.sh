#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f infra/compose.yaml)
stamp="$(date -u +%Y%m%d%H%M%S)"
restore_db="pci_restore_${stamp}_$$"
fixture_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
fixture_contribution_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
fixture_version_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
fixture_production_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
dump_file="$(mktemp -t observainova-backup-XXXXXX.sql)"

if [[ ! "$restore_db" =~ ^pci_restore_[0-9]{14}_[0-9]+$ ]]; then
  echo "Unsafe temporary database name" >&2
  exit 1
fi

cleanup() {
  "${compose[@]}" exec -T postgres psql -U pci -d pci -v ON_ERROR_STOP=1 -c "DELETE FROM published_contributions WHERE id = '$fixture_id';" >/dev/null 2>&1 || true
  "${compose[@]}" exec -T postgres dropdb -U pci --if-exists "$restore_db" >/dev/null 2>&1 || true
  rm -f -- "$dump_file"
}
trap cleanup EXIT

command -v docker >/dev/null || { echo "Docker is required for backup/restore smoke verification." >&2; exit 1; }
"${compose[@]}" exec -T postgres psql -U pci -d pci -v ON_ERROR_STOP=1 <<SQL
INSERT INTO published_contributions (
  id, scientific_contribution_id, contribution_version_id, production_id, version,
  scientific_values, approved_groundings, active
) VALUES (
  '$fixture_id', '$fixture_contribution_id',
  '$fixture_version_id', '$fixture_production_id',
  1, '{"description":"backup-smoke"}'::jsonb, '[]'::jsonb, true
);
SQL
"${compose[@]}" exec -T postgres pg_dump -U pci -d pci --no-owner --no-privileges > "$dump_file"
"${compose[@]}" exec -T postgres createdb -U pci "$restore_db"
"${compose[@]}" exec -T postgres psql -U pci -d "$restore_db" -v ON_ERROR_STOP=1 < "$dump_file"
"${compose[@]}" exec -T postgres psql -U pci -d "$restore_db" -v ON_ERROR_STOP=1 -At <<SQL
SELECT version_num = '0019_return_correction_workflow' AS revision_ok FROM alembic_version \gset
\if :revision_ok
\else
  \quit 1
\endif
SELECT COUNT(*) = 5 AS tables_ok FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('source_documents','candidate_contributions','sampling_runs','scientific_contributions','published_contributions') \gset
\if :tables_ok
\else
  \quit 1
\endif
SELECT COALESCE(bool_and(scientific_values->>'description' = 'backup-smoke'), false) AS fixture_ok FROM published_contributions WHERE id = '$fixture_id' \gset
\if :fixture_ok
\else
  \quit 1
\endif
SELECT 'backup-restore-smoke-ok';
SQL
