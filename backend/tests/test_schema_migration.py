"""ensure_schema_columns(): lightweight, additive-only migration for columns added to models later.

Every test uses its own temp SQLite file; the application's shared engine is only touched through
monkeypatching `connection._engine` in the init_db test.
"""
import logging
import os

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, text

from backend.database import connection
from backend.database.connection import Base, ensure_schema_columns

# experiment_trials as it looked before result_hash existed.
OLD_EXPERIMENT_TRIALS = """
CREATE TABLE experiment_trials (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    label VARCHAR(200),
    parent_trial_id VARCHAR(32),
    spec_json TEXT NOT NULL,
    spec_hash VARCHAR(64) NOT NULL,
    dataset_hash VARCHAR(64),
    dataset_request_json TEXT,
    engine_version VARCHAR(20) NOT NULL,
    environment_json TEXT,
    seed INTEGER NOT NULL,
    status VARCHAR(12) NOT NULL,
    error_code VARCHAR(40),
    error_message VARCHAR(300),
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    result_json TEXT,
    headline_json TEXT,
    ledger_hash VARCHAR(64),
    monte_carlo_hash VARCHAR(64),
    CONSTRAINT ck_experiment_trials_status CHECK (status IN ('completed', 'failed'))
)
"""
OLD_INDEXES = [
    "CREATE INDEX idx_experiment_trials_user_started ON experiment_trials (user_id, started_at)",
    "CREATE INDEX idx_experiment_trials_parent ON experiment_trials (parent_trial_id)",
]


@pytest.fixture(autouse=True)
def _fresh_warning_state(monkeypatch):
    monkeypatch.setattr(connection, "_warned_schema_columns", set())


@pytest.fixture
def engine(tmp_path):
    eng = create_engine("sqlite:///" + os.path.join(tmp_path, "mig.db"))
    yield eng
    eng.dispose()


def _columns(engine, table):
    return {c["name"]: c for c in inspect(engine).get_columns(table)}


def _structure(engine, table):
    insp = inspect(engine)
    return {
        "pk": insp.get_pk_constraint(table),
        "indexes": sorted((i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in insp.get_indexes(table)),
        "checks": sorted((c["name"], c["sqltext"]) for c in insp.get_check_constraints(table)),
        "fks": insp.get_foreign_keys(table),
        "uniques": insp.get_unique_constraints(table),
    }


def _make_old_table(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(OLD_EXPERIMENT_TRIALS)
        for ddl in OLD_INDEXES:
            conn.exec_driver_sql(ddl)
        conn.execute(text(
            "INSERT INTO experiment_trials (id, user_id, spec_json, spec_hash, engine_version, seed, "
            "status, started_at, ledger_hash) VALUES ('t1', 'guest_x', '{}', 'sh', '1.0', 7, "
            "'completed', '2024-01-01 00:00:00', 'lh')"
        ))


def test_adds_result_hash_to_old_experiment_trials_table(engine):
    from backend.database import models  # noqa: F401  (populate Base.metadata)

    _make_old_table(engine)
    assert "result_hash" not in _columns(engine, "experiment_trials")
    before = _structure(engine, "experiment_trials")

    summary = ensure_schema_columns(engine)

    cols = _columns(engine, "experiment_trials")
    assert "result_hash" in cols and cols["result_hash"]["nullable"] is True
    assert "experiment_trials.result_hash" in summary["added"]
    # existing row preserved, new column NULL
    row = engine.connect().execute(text("SELECT id, user_id, seed, ledger_hash, result_hash FROM experiment_trials")).all()
    assert [tuple(r) for r in row] == [("t1", "guest_x", 7, "lh", None)]
    # indexes / constraints / pk untouched
    assert _structure(engine, "experiment_trials") == before
    # new column is writable
    with engine.begin() as conn:
        conn.execute(text("UPDATE experiment_trials SET result_hash = 'abc' WHERE id = 't1'"))
    assert engine.connect().execute(text("SELECT result_hash FROM experiment_trials")).scalar() == "abc"


def test_second_run_is_a_noop(engine):
    from backend.database import models  # noqa: F401

    _make_old_table(engine)
    ensure_schema_columns(engine)
    snapshot = (_columns(engine, "experiment_trials").keys(), _structure(engine, "experiment_trials"))
    second = ensure_schema_columns(engine)
    assert second == {"added": [], "skipped": []}
    assert (_columns(engine, "experiment_trials").keys(), _structure(engine, "experiment_trials")) == snapshot


def test_tables_that_do_not_exist_are_left_alone(engine):
    from backend.database import models  # noqa: F401

    assert ensure_schema_columns(engine) == {"added": [], "skipped": []}
    assert inspect(engine).get_table_names() == []  # ensure never creates tables


def test_up_to_date_database_is_unchanged(engine):
    from backend.database import models  # noqa: F401

    Base.metadata.create_all(engine)
    assert ensure_schema_columns(engine) == {"added": [], "skipped": []}


def test_init_db_runs_migration_after_create_all(engine, monkeypatch):
    _make_old_table(engine)
    monkeypatch.setattr(connection, "_engine", engine)
    connection.init_db()
    assert "result_hash" in _columns(engine, "experiment_trials")
    assert engine.connect().execute(text("SELECT count(*) FROM experiment_trials")).scalar() == 1
    connection.init_db()  # idempotent
    assert "result_hash" in _columns(engine, "experiment_trials")


def _meta_with(*columns):
    meta = MetaData()
    Table("widgets", meta, Column("id", Integer, primary_key=True), Column("name", String(20)), *columns)
    return meta


def _make_widgets(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE widgets (id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(20))")
        conn.exec_driver_sql("INSERT INTO widgets (id, name) VALUES (1, 'a')")


def test_not_null_without_default_is_skipped_with_warning(engine, caplog):
    _make_widgets(engine)
    meta = _meta_with(Column("required", String(10), nullable=False), Column("optional", String(10)))
    with caplog.at_level(logging.WARNING, logger=connection.logger.name):
        summary = ensure_schema_columns(engine, metadata=meta)
    cols = _columns(engine, "widgets")
    assert "required" not in cols  # skipped, never dropped / half-added
    assert "optional" in cols  # other columns still processed
    assert [label for label, _ in summary["skipped"]] == ["widgets.required"]
    assert summary["added"] == ["widgets.optional"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("widgets.required" in r.getMessage() and "NOT NULL" in r.getMessage() for r in warnings)
    # repeated runs keep skipping without error, but the warning is logged once per process
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=connection.logger.name):
        again = ensure_schema_columns(engine, metadata=meta)
        ensure_schema_columns(engine, metadata=meta)
    assert again["added"] == [] and [l for l, _ in again["skipped"]] == ["widgets.required"]
    assert not [r for r in caplog.records if "widgets.required" in r.getMessage()]


def test_not_null_with_defaults_is_added_and_backfilled(engine):
    _make_widgets(engine)
    meta = _meta_with(
        Column("qty", Integer, nullable=False, default=5),
        Column("kind", String(10), nullable=False, server_default="basic"),
        Column("note", String(10), nullable=False, default="it's"),
    )
    summary = ensure_schema_columns(engine, metadata=meta)
    assert sorted(summary["added"]) == ["widgets.kind", "widgets.note", "widgets.qty"]
    row = engine.connect().execute(text("SELECT name, qty, kind, note FROM widgets")).one()
    assert tuple(row) == ("a", 5, "basic", "it's")
    assert all(not _columns(engine, "widgets")[c]["nullable"] for c in ("qty", "kind", "note"))


def test_callable_default_not_null_is_skipped(engine):
    _make_widgets(engine)
    meta = _meta_with(Column("stamp", String(10), nullable=False, default=lambda: "x"))
    summary = ensure_schema_columns(engine, metadata=meta)
    assert summary["added"] == [] and [l for l, _ in summary["skipped"]] == ["widgets.stamp"]


def test_missing_primary_key_column_is_skipped(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE widgets (name VARCHAR(20))")
    meta = MetaData()
    Table("widgets", meta, Column("id", Integer, primary_key=True), Column("name", String(20)))
    summary = ensure_schema_columns(engine, metadata=meta)
    assert summary["added"] == [] and [l for l, _ in summary["skipped"]] == ["widgets.id"]


def test_existing_columns_are_never_altered_or_dropped(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE widgets (id INTEGER NOT NULL PRIMARY KEY, name TEXT, legacy TEXT)")
        conn.exec_driver_sql("INSERT INTO widgets VALUES (1, 'a', 'keep me')")
    meta = _meta_with()  # model says name is VARCHAR(20) and has no `legacy`
    assert ensure_schema_columns(engine, metadata=meta) == {"added": [], "skipped": []}
    cols = _columns(engine, "widgets")
    assert set(cols) == {"id", "name", "legacy"} and str(cols["name"]["type"]) == "TEXT"
    assert engine.connect().execute(text("SELECT legacy FROM widgets")).scalar() == "keep me"


def test_failure_is_logged_redacted_and_not_raised(engine, caplog, monkeypatch):
    _make_widgets(engine)
    meta = _meta_with(Column("extra", String(10)))
    secret = "s3cr3tpassw0rd"

    class Boom(Exception):
        pass

    # redact_db_secrets masks the credentials of the configured/active database URL.
    monkeypatch.setattr(connection, "_active_database_url", f"postgresql://user:{secret}@db.example.com/app")

    original = type(engine).begin

    def failing_begin(self, *a, **k):
        raise Boom(f"could not connect postgresql://user:{secret}@db.example.com/app")

    monkeypatch.setattr(type(engine), "begin", failing_begin)
    with caplog.at_level(logging.WARNING, logger=connection.logger.name):
        summary = ensure_schema_columns(engine, metadata=meta)
    monkeypatch.setattr(type(engine), "begin", original)
    assert summary["added"] == [] and summary["skipped"] == [("widgets.extra", "ALTER TABLE failed")]
    assert secret not in caplog.text and "db.example.com" in caplog.text
