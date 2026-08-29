from types import SimpleNamespace

from kquant_crypto.db.migrations import LATEST_SCHEMA_VERSION
from kquant_crypto.staging import (
    postgres_migration_plan,
    postgres_sql,
    staging_status,
    verify_staging,
)


def test_staging_is_fail_closed_without_a_dsn():
    value = staging_status(SimpleNamespace(staging_database_url=""))
    assert value["status"] == "not_configured"
    assert value["postgres_configured"] is False
    assert value["dsn_exposed"] is False
    assert verify_staging(SimpleNamespace(staging_database_url=""))["connection_status"] == "not_configured"


def test_postgres_translation_and_plan_are_versioned_without_secrets():
    translated = postgres_sql("CREATE TABLE x (id INTEGER PRIMARY KEY AUTOINCREMENT); INSERT OR IGNORE INTO x VALUES (1);")
    assert "AUTOINCREMENT" not in translated
    assert "BIGSERIAL PRIMARY KEY" in translated
    assert "INSERT OR IGNORE" not in translated
    plan = postgres_migration_plan()
    assert len(plan) == LATEST_SCHEMA_VERSION
    assert plan[-1]["version"] == LATEST_SCHEMA_VERSION
    assert all("password" not in str(item).lower() for item in plan)


def test_invalid_staging_scheme_does_not_attempt_connection():
    result = verify_staging(SimpleNamespace(staging_database_url="sqlite:///tmp/nope"))
    assert result["status"] == "invalid_database_url"
    assert result["connection_status"] == "blocked"
