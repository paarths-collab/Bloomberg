"""Regression tests for run_init_sql(): comment-prefixed statements must not be dropped.

Every test uses its own temp SQLite engine, so nothing depends on (or leaks into) the
application's shared engine.
"""
import logging
import os
import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

from backend.database import connection
from backend.database.connection import (
    _adapt_statement_for_dialect,
    _escape_percent_for_paramstyle,
    _is_already_exists_error,
    _split_sql_statements,
    run_init_sql,
)

INIT_SQL_PATH = os.path.join(os.path.dirname(connection.__file__), "init.sql")

EXPECTED_TABLES = {
    "fred_data",
    "fred_series_metadata",
    "sector_news_item",
    "sector_snapshot",
    "sector_score",
    "user_profiles",
}
EXPECTED_INDEXES = {
    "idx_fred_series_type",
    "idx_fred_date",
    "idx_fred_series_date",
    "idx_sector_news_market_sector_date",
    "idx_sector_snapshot_market_sector_asof",
    "idx_sector_score_market_sector_asof",
    "idx_user_profiles_user_id",
}
EXPECTED_TRIGGERS = {"update_fred_data_updated_at", "update_user_profiles_updated_at"}
USER_PROFILE_COLUMNS = [
    "id", "user_id", "name", "age", "monthly_income", "monthly_savings", "risk_tolerance",
    "horizon_years", "primary_goal", "existing_investments", "market", "created_at", "updated_at",
]


@pytest.fixture
def sqlite_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'init_test.db'}")
    yield engine
    engine.dispose()


def _schema_objects(engine, kind):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type = :kind AND name NOT LIKE 'sqlite_%'"),
            {"kind": kind},
        )
        return {r[0] for r in rows}


# --- splitter --------------------------------------------------------------------------------

def test_splitter_keeps_statement_preceded_by_comment_block():
    script = (
        "-- header comment\n"
        "-- second comment line\n"
        "CREATE TABLE a (x INTEGER);\n"
        "\n"
        "-- another\n"
        "CREATE INDEX idx_a ON a(x);\n"
    )
    assert _split_sql_statements(script) == [
        "CREATE TABLE a (x INTEGER)",
        "CREATE INDEX idx_a ON a(x)",
    ]


def test_splitter_drops_comment_only_chunks_and_block_comments():
    script = (
        "-- nothing here;\n"
        "/* block; comment */\n"
        ";\n"
        "/* leading */ CREATE TABLE b (x INTEGER); -- trailing; comment\n"
        "-- final comment with no statement after it\n"
    )
    assert _split_sql_statements(script) == ["CREATE TABLE b (x INTEGER)"]


def test_splitter_strips_inline_comments():
    script = "CREATE TABLE c (\n    x INTEGER, -- the x; column\n    y TEXT /* inline; block */\n);"
    (stmt,) = _split_sql_statements(script)
    assert "--" not in stmt and "/*" not in stmt and "the x" not in stmt
    assert stmt.startswith("CREATE TABLE c (") and stmt.endswith(")")
    assert "x INTEGER," in stmt and "y TEXT" in stmt


def test_splitter_keeps_comment_markers_and_semicolons_inside_string_literals():
    script = (
        "INSERT INTO t VALUES ('a;b', 'it''s -- not a comment; really', '/* nor this */');\n"
        'CREATE TABLE "we;ird--name" (x INTEGER);\n'
        "SELECT 2;"
    )
    stmts = _split_sql_statements(script)
    assert stmts == [
        "INSERT INTO t VALUES ('a;b', 'it''s -- not a comment; really', '/* nor this */')",
        'CREATE TABLE "we;ird--name" (x INTEGER)',
        "SELECT 2",
    ]


def test_splitter_keeps_trigger_body_with_semicolons_as_one_statement():
    script = (
        "-- trigger comment\n"
        "CREATE TRIGGER IF NOT EXISTS trg\n"
        "    AFTER UPDATE ON t\n"
        "    FOR EACH ROW\n"
        "    BEGIN\n"
        "        UPDATE t SET u = CURRENT_TIMESTAMP WHERE rowid = NEW.rowid; -- body; comment\n"
        "        SELECT CASE WHEN NEW.x > 1 THEN 1 ELSE 0 END;\n"
        "    END;\n"
        "\n"
        "-- after\n"
        "CREATE TABLE d (x INTEGER);\n"
    )
    stmts = _split_sql_statements(script)
    assert len(stmts) == 2
    trigger, table = stmts
    assert trigger.startswith("CREATE TRIGGER IF NOT EXISTS trg")
    assert trigger.rstrip().upper().endswith("END")
    assert "UPDATE t SET u = CURRENT_TIMESTAMP WHERE rowid = NEW.rowid;" in trigger
    assert "CASE WHEN NEW.x > 1 THEN 1 ELSE 0 END;" in trigger
    assert "body; comment" not in trigger
    assert table == "CREATE TABLE d (x INTEGER)"


def test_splitter_handles_dollar_quoted_bodies_on_postgres_only():
    script = (
        "CREATE FUNCTION f() RETURNS int AS $$ BEGIN RETURN 1; END; $$ LANGUAGE plpgsql;\n"
        "CREATE TABLE e (x INTEGER);"
    )
    pg = _split_sql_statements(script, "postgresql")
    assert len(pg) == 2
    assert "RETURN 1; END;" in pg[0] and pg[0].endswith("plpgsql")
    assert pg[1] == "CREATE TABLE e (x INTEGER)"


def test_splitter_last_statement_without_terminator_is_kept():
    assert _split_sql_statements("-- c\nSELECT 1") == ["SELECT 1"]


def test_real_init_sql_splits_into_expected_statements():
    with open(INIT_SQL_PATH, encoding="utf-8") as f:
        statements = _split_sql_statements(f.read())
    assert all(s and "--" not in s for s in statements)
    created = [s for s in statements if s.upper().startswith("CREATE TABLE")]
    assert len(created) == len(EXPECTED_TABLES)
    assert sum(s.upper().startswith("CREATE TRIGGER") for s in statements) == len(EXPECTED_TRIGGERS)
    assert sum(s.upper().startswith("CREATE INDEX") for s in statements) == len(EXPECTED_INDEXES)
    assert sum(s.upper().startswith("INSERT") for s in statements) == 1


# --- dialect adaptation -----------------------------------------------------------------------

def test_non_sqlite_dialect_adaptation():
    assert _adapt_statement_for_dialect("CREATE TRIGGER IF NOT EXISTS t AFTER UPDATE ON x BEGIN SELECT 1; END", "postgresql") is None
    assert (
        _adapt_statement_for_dialect("CREATE TABLE s (id INTEGER PRIMARY KEY AUTOINCREMENT)", "postgresql")
        == "CREATE TABLE s (id BIGSERIAL PRIMARY KEY)"
    )
    assert (
        _adapt_statement_for_dialect("INSERT OR IGNORE INTO m (a) VALUES (1)", "postgresql")
        == "INSERT INTO m (a) VALUES (1) ON CONFLICT DO NOTHING"
    )
    # Plain INSERTs and index statements are never rewritten to swallow conflicts.
    assert _adapt_statement_for_dialect("INSERT INTO m (a) VALUES (1)", "postgresql") == "INSERT INTO m (a) VALUES (1)"
    idx = "CREATE INDEX IF NOT EXISTS i ON t(c)"
    assert _adapt_statement_for_dialect(idx, "postgresql") == idx
    # SQLite is passed through untouched.
    sqlite_stmt = "INSERT OR IGNORE INTO m (a) VALUES (1)"
    assert _adapt_statement_for_dialect(sqlite_stmt, "sqlite") == sqlite_stmt


def test_every_real_statement_adapts_cleanly_for_postgres():
    with open(INIT_SQL_PATH, encoding="utf-8") as f:
        statements = _split_sql_statements(f.read(), "postgresql")
    adapted = [a for a in (_adapt_statement_for_dialect(s, "postgresql") for s in statements) if a]
    assert len(adapted) == len(statements) - len(EXPECTED_TRIGGERS)
    joined = "\n".join(adapted)
    assert "AUTOINCREMENT" not in joined and "INSERT OR IGNORE" not in joined
    assert joined.count("ON CONFLICT DO NOTHING") == 1
    assert "BIGSERIAL PRIMARY KEY" in joined
    for stmt in adapted:
        if stmt.upper().startswith("CREATE INDEX"):
            assert "ON CONFLICT" not in stmt


# --- run_init_sql against a fresh SQLite DB ---------------------------------------------------

def test_fresh_database_gets_every_table_index_and_trigger(sqlite_engine):
    assert _schema_objects(sqlite_engine, "table") == set()

    summary = run_init_sql(engine=sqlite_engine)

    assert summary["failed"] == 0
    assert EXPECTED_TABLES <= _schema_objects(sqlite_engine, "table")
    assert EXPECTED_INDEXES <= _schema_objects(sqlite_engine, "index")
    assert EXPECTED_TRIGGERS <= _schema_objects(sqlite_engine, "trigger")


def test_user_profiles_has_the_declared_columns_and_constraints(sqlite_engine):
    run_init_sql(engine=sqlite_engine)
    columns = {c["name"]: c for c in inspect(sqlite_engine).get_columns("user_profiles")}
    assert list(columns) == USER_PROFILE_COLUMNS
    assert columns["user_id"]["nullable"] is False
    assert columns["id"]["primary_key"] == 1

    uniques = inspect(sqlite_engine).get_unique_constraints("user_profiles")
    indexes = inspect(sqlite_engine).get_indexes("user_profiles")
    assert any(u["column_names"] == ["user_id"] for u in uniques) or any(
        i["unique"] and i["column_names"] == ["user_id"] for i in indexes
    )

    with sqlite_engine.begin() as conn:
        conn.execute(text("INSERT INTO user_profiles (user_id) VALUES ('u1')"))
        row = conn.execute(
            text("SELECT risk_tolerance, horizon_years, market, created_at FROM user_profiles")
        ).one()
        assert row[:3] == ("moderate", 5, "US") and row[3]
        with pytest.raises(Exception):
            conn.execute(text("INSERT INTO user_profiles (user_id) VALUES ('u1')"))


def test_seed_metadata_rows_are_inserted(sqlite_engine):
    run_init_sql(engine=sqlite_engine)
    with sqlite_engine.connect() as conn:
        ids = {r[0] for r in conn.execute(text("SELECT series_id FROM fred_series_metadata"))}
    assert {"SP500", "DJIA", "NASDAQ100", "DGS10", "UNRATE", "GOLDAMGBD228NLBM"} <= ids
    assert len(ids) == 13


def test_updated_at_triggers_work(sqlite_engine):
    run_init_sql(engine=sqlite_engine)
    with sqlite_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO user_profiles (user_id, created_at, updated_at) "
                 "VALUES ('u', '2000-01-01 00:00:00', '2000-01-01 00:00:00')")
        )
        conn.execute(text("UPDATE user_profiles SET name = 'x' WHERE user_id = 'u'"))
        updated = conn.execute(text("SELECT updated_at FROM user_profiles WHERE user_id = 'u'")).scalar_one()
    assert updated != "2000-01-01 00:00:00"


def test_run_twice_is_idempotent_and_preserves_data(sqlite_engine):
    run_init_sql(engine=sqlite_engine)
    with sqlite_engine.begin() as conn:
        conn.execute(text("INSERT INTO user_profiles (user_id, name) VALUES ('keep', 'Kept')"))
    before = {k: _schema_objects(sqlite_engine, k) for k in ("table", "index", "trigger")}

    second = run_init_sql(engine=sqlite_engine)

    assert second["failed"] == 0
    assert {k: _schema_objects(sqlite_engine, k) for k in ("table", "index", "trigger")} == before
    with sqlite_engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM user_profiles WHERE user_id = 'keep'")).scalar_one() == "Kept"
        assert conn.execute(text("SELECT COUNT(*) FROM fred_series_metadata")).scalar_one() == 13


def test_runs_after_orm_create_all_without_breaking_orm_tables(sqlite_engine):
    from backend.database import models  # noqa: F401  (registers ORM tables on Base.metadata)

    connection.Base.metadata.create_all(bind=sqlite_engine)
    summary = run_init_sql(engine=sqlite_engine)
    assert summary["failed"] == 0
    assert "user_profiles" in _schema_objects(sqlite_engine, "table")
    with sqlite_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM fred_series_metadata")).scalar_one() == 13


def test_application_engine_is_not_touched_by_isolated_runs(sqlite_engine):
    run_init_sql(engine=sqlite_engine)
    assert str(sqlite_engine.url) != str(connection.get_engine().url)


# --- error handling & logging -----------------------------------------------------------------

def test_bad_statement_does_not_stop_later_statements_and_is_logged_as_error(sqlite_engine, tmp_path, caplog):
    script = tmp_path / "bad.sql"
    script.write_text(
        "-- first\n"
        "CREATE TABLE ok1 (x INTEGER);\n"
        "-- this one is broken\n"
        "CREATE TABLE broken (x INTEGER;\n"
        "-- but the next is fine\n"
        "CREATE TABLE ok2 (x INTEGER);\n"
        "CREATE TABLE ok1 (x INTEGER);\n",  # plain duplicate (no IF NOT EXISTS)
        encoding="utf-8",
    )
    with caplog.at_level(logging.INFO, logger=connection.logger.name):
        summary = run_init_sql(engine=sqlite_engine, sql_path=str(script))

    assert summary == {"executed": 2, "already_exists": 1, "failed": 1, "skipped": 0}
    assert {"ok1", "ok2"} <= _schema_objects(sqlite_engine, "table")
    assert "broken" not in _schema_objects(sqlite_engine, "table")

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "broken" in errors[0].getMessage()
    already = [r for r in caplog.records if "already applied" in r.getMessage()]
    assert len(already) == 1 and already[0].levelno == logging.INFO


def test_error_logs_redact_database_secrets(sqlite_engine, tmp_path, caplog, monkeypatch):
    secret_url = "postgresql://alice:s3cr3t-pw@db.internal:5432/prod"
    monkeypatch.setattr(connection, "DATABASE_URL", secret_url)
    script = tmp_path / "leak.sql"
    script.write_text("SELECT * FROM missing_s3cr3t-pw_table;\nSELECT 'postgresql://alice:s3cr3t-pw@db.internal:5432/prod' FROM nope;\n", encoding="utf-8")
    with caplog.at_level(logging.INFO, logger=connection.logger.name):
        summary = run_init_sql(engine=sqlite_engine, sql_path=str(script))
    assert summary["failed"] == 2
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "s3cr3t-pw" not in logged and "alice" not in logged


def test_missing_init_sql_does_not_crash(sqlite_engine, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=connection.logger.name):
        summary = run_init_sql(engine=sqlite_engine, sql_path=str(tmp_path / "nope.sql"))
    assert summary == {"executed": 0, "already_exists": 0, "failed": 0, "skipped": 0}
    assert any("not found" in r.getMessage() for r in caplog.records)


def test_colon_in_literal_is_not_treated_as_bind_parameter(sqlite_engine, tmp_path):
    script = tmp_path / "colon.sql"
    script.write_text(
        "CREATE TABLE notes (body TEXT);\nINSERT INTO notes VALUES ('ratio :1 and note:text');\n",
        encoding="utf-8",
    )
    assert run_init_sql(engine=sqlite_engine, sql_path=str(script))["failed"] == 0
    with sqlite_engine.connect() as conn:
        assert conn.execute(text("SELECT body FROM notes")).scalar_one() == "ratio :1 and note:text"


class _FakeDriverError(Exception):
    def __init__(self, message, pgcode=None):
        super().__init__(message)
        self.pgcode = pgcode


def test_already_exists_classifier():
    assert _is_already_exists_error(sqlite3.OperationalError("table x already exists"))
    assert _is_already_exists_error(sqlite3.OperationalError("index idx_a already exists"))
    assert _is_already_exists_error(sqlite3.OperationalError("trigger trg already exists"))
    assert _is_already_exists_error(Exception("duplicate column name: y"))
    assert _is_already_exists_error(Exception('relation "x" already exists'))
    assert not _is_already_exists_error(Exception("no such table: z"))
    # Data errors that merely contain the phrase are real failures.
    assert not _is_already_exists_error(Exception("DETAIL:  Key (a)=(1) already exists."))
    assert not _is_already_exists_error(
        Exception('duplicate key value violates unique constraint "t_pkey"; Key (a)=(1) already exists.')
    )
    assert not _is_already_exists_error(sqlite3.IntegrityError("UNIQUE constraint failed: t.a"))


def test_already_exists_classifier_uses_sqlstate_when_available():
    assert _is_already_exists_error(_FakeDriverError("whatever", pgcode="42P07"))
    assert _is_already_exists_error(_FakeDriverError("whatever", pgcode="42701"))
    # unique_violation: message says "already exists" but it is a real failure.
    assert not _is_already_exists_error(_FakeDriverError("Key (a)=(1) already exists.", pgcode="23505"))
    # invalid_table_definition (e.g. multiple primary keys) is a real failure.
    assert not _is_already_exists_error(_FakeDriverError("multiple primary keys for table", pgcode="42P16"))
    # A code decides even if the text looks like "already exists".
    assert not _is_already_exists_error(_FakeDriverError("table x already exists", pgcode="42601"))


def test_duplicate_insert_into_primary_key_table_is_a_failure_logged_at_error(sqlite_engine, tmp_path, caplog):
    script = tmp_path / "dup.sql"
    script.write_text(
        "CREATE TABLE pk (a INTEGER PRIMARY KEY);\n"
        "INSERT INTO pk (a) VALUES (1);\n"
        "INSERT INTO pk (a) VALUES (1);\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.INFO, logger=connection.logger.name):
        summary = run_init_sql(engine=sqlite_engine, sql_path=str(script))
    assert summary == {"executed": 2, "already_exists": 0, "failed": 1, "skipped": 0}
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "INSERT INTO pk" in errors[0].getMessage()
    assert not [r for r in caplog.records if "already applied" in r.getMessage()]


# --- percent escaping, trigger edge cases, adaptation edge cases ------------------------------

def test_percent_escaping_depends_on_paramstyle():
    stmt = "INSERT INTO t VALUES ('100%', 'a%sb')"
    assert _escape_percent_for_paramstyle(stmt, "pyformat") == "INSERT INTO t VALUES ('100%%', 'a%%sb')"
    assert _escape_percent_for_paramstyle(stmt, "format") == "INSERT INTO t VALUES ('100%%', 'a%%sb')"
    assert _escape_percent_for_paramstyle(stmt, "qmark") == stmt
    assert _escape_percent_for_paramstyle(stmt, "named") == stmt


def test_percent_literal_executes_on_sqlite(sqlite_engine, tmp_path):
    script = tmp_path / "pct.sql"
    script.write_text("CREATE TABLE p (v TEXT);\nINSERT INTO p VALUES ('100% sure');\n", encoding="utf-8")
    assert run_init_sql(engine=sqlite_engine, sql_path=str(script))["failed"] == 0
    with sqlite_engine.connect() as conn:
        assert conn.execute(text("SELECT v FROM p")).scalar_one() == "100% sure"


def test_splitter_trigger_body_with_qualified_end_identifier():
    script = (
        "CREATE TRIGGER trg AFTER UPDATE ON t BEGIN\n"
        "    UPDATE t SET a = NEW.end; \n"
        "    UPDATE t SET b = OLD.END;\n"
        "END;\n"
        "CREATE TABLE after_it (x INTEGER);"
    )
    stmts = _split_sql_statements(script)
    assert len(stmts) == 2
    assert "SET b = OLD.END;" in stmts[0] and stmts[0].endswith("END")
    assert stmts[1] == "CREATE TABLE after_it (x INTEGER)"


def test_splitter_recognises_create_or_replace_trigger():
    script = (
        "CREATE OR REPLACE TRIGGER trg AFTER UPDATE ON t BEGIN\n"
        "    UPDATE t SET a = 1;\n"
        "END;\n"
        "SELECT 1;"
    )
    stmts = _split_sql_statements(script)
    assert len(stmts) == 2 and stmts[0].startswith("CREATE OR REPLACE TRIGGER")
    assert _adapt_statement_for_dialect(stmts[0], "postgresql") is None


def test_adaptation_leaves_string_literals_alone():
    stmt = "INSERT INTO notes (body) VALUES ('use INTEGER PRIMARY KEY AUTOINCREMENT here; INSERT OR IGNORE INTO x')"
    assert _adapt_statement_for_dialect(stmt, "postgresql") == stmt
    stmt = 'CREATE TABLE q (id INTEGER PRIMARY KEY AUTOINCREMENT, note TEXT DEFAULT \'AUTOINCREMENT\')'
    assert _adapt_statement_for_dialect(stmt, "postgresql") == (
        "CREATE TABLE q (id BIGSERIAL PRIMARY KEY, note TEXT DEFAULT 'AUTOINCREMENT')"
    )
    # An ON CONFLICT mentioned only inside a literal does not count as a conflict clause.
    assert _adapt_statement_for_dialect(
        "INSERT OR IGNORE INTO m (a) VALUES ('ON CONFLICT')", "postgresql"
    ) == "INSERT INTO m (a) VALUES ('ON CONFLICT') ON CONFLICT DO NOTHING"


@pytest.mark.parametrize(
    "stmt",
    [
        "INSERT OR REPLACE INTO m (a) VALUES (1)",
        "REPLACE INTO m (a) VALUES (1)",
        "INSERT OR ABORT INTO m (a) VALUES (1)",
    ],
)
def test_insert_or_replace_is_skipped_with_warning_on_postgres(stmt, caplog):
    with caplog.at_level(logging.WARNING, logger=connection.logger.name):
        assert _adapt_statement_for_dialect(stmt, "postgresql") is None
    assert any(r.levelno == logging.WARNING and "not supported" in r.getMessage() for r in caplog.records)
    # SQLite keeps it as written.
    assert _adapt_statement_for_dialect(stmt, "sqlite") == stmt
