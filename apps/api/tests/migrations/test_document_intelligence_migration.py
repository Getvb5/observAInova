import pytest
from alembic.config import Config

from alembic import command


def test_document_intelligence_migration_contains_versioned_append_only_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    ddl = " ".join(capsys.readouterr().out.split())

    assert "ADD COLUMN academic_program TEXT" in ddl
    assert "ADD COLUMN knowledge_areas JSONB" in ddl
    assert "CREATE TABLE source_documents" in ddl
    assert "CREATE TABLE document_text_versions" in ddl
    assert "CREATE TABLE document_pages" in ddl
    assert "UNIQUE (production_version_id, version)" in ddl
    assert "UNIQUE (document_text_version_id, page_number)" in ddl
    assert "BEFORE UPDATE OR DELETE ON document_text_versions" in ddl
    assert "BEFORE UPDATE OR DELETE ON document_pages" in ddl
    assert "CREATE TYPE source_document_status AS ENUM" in ddl
    assert "CREATE TYPE document_text_scope AS ENUM" in ddl
    assert "CREATE TYPE text_extraction_method AS ENUM" in ddl
