from sqlalchemy import inspect

EXPECTED_TABLES = {
    "users",
    "batches",
    "orders",
    "order_assets",
    "assignments",
    "result_versions",
    "approval_requests",
    "approval_decisions",
    "external_observations",
    "operations",
    "workflow_events",
    "outbox",
    "dead_letters",
    "printerval_assignment_requests",
    "alembic_version",
}


def test_migration_creates_all_tables(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES.issubset(tables)
