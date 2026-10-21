import os
import re
import logging
from contextlib import contextmanager
from urllib.parse import unquote

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

# =====================================================
# DATABASE CONFIG
# =====================================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./boomerang.db")
SQLITE_FALLBACK_URL = os.getenv("SQLITE_FALLBACK_URL", "sqlite:///./boomerang.db")


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable ("true" enables it)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


# Explicit opt-in: silently switching a hosted service from a configured remote
# database to a local SQLite file would create divergent, ephemeral data.
DB_FALLBACK_TO_SQLITE = _env_flag("DB_FALLBACK_TO_SQLITE", default=False)

_active_database_url = DATABASE_URL
_fallback_active = False


def _engine_options_for(db_url: str):
    options = {
        "pool_pre_ping": True,
        "echo": os.getenv("SQL_ECHO", "false").lower() == "true",
    }

    if not db_url.startswith("sqlite"):
        options.update({
            "pool_size": int(os.getenv("DB_POOL_SIZE", 5)),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", 10)),
            "pool_recycle": 1800,
        })
    return options


def _create_engine_for(db_url: str):
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(db_url, connect_args=connect_args, **_engine_options_for(db_url))


_SENSITIVE_QUERY_PARAM_RE = re.compile(
    r"(?<![A-Za-z0-9_])(sslpassword|password|passwd|pwd)=([^&\s#'\"]*)",
    re.IGNORECASE,
)
_MIN_FREE_TEXT_SECRET_LEN = 3


def _mask_query_secrets(text_value: str) -> str:
    """Mask the values of password-like query parameters (password=, passwd=, sslpassword=, pwd=)."""
    return _SENSITIVE_QUERY_PARAM_RE.sub(lambda m: f"{m.group(1)}=***", text_value)


def _split_userinfo(rest: str):
    """Split the part of a URL after "://" into (userinfo or None, remainder).

    The query string is excluded when looking for the credentials separator so an "@" in a
    query value cannot be mistaken for it, while the LAST "@" before the query is used so
    passwords containing "@" are fully covered.
    """
    base, sep, query = rest.partition("?")
    if "@" in base:
        userinfo, tail_base = base.rsplit("@", 1)
        return userinfo, tail_base + sep + query
    return None, rest


def _safe_db_url(db_url: str) -> str:
    """Return a loggable form of a DB URL with username, password and query-string passwords masked."""
    if "://" not in db_url:
        return "<unparseable database url>"
    prefix, rest = db_url.split("://", 1)
    userinfo, tail = _split_userinfo(rest)
    if userinfo is not None:
        return _mask_query_secrets(f"{prefix}://***:***@{tail}")
    return _mask_query_secrets(db_url)


def _replace_standalone(text_value: str, token: str) -> str:
    """Replace `token` only where it is not embedded in a longer word-like run."""
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])"
    return re.sub(pattern, "***", text_value)


def redact_db_secrets(message: str) -> str:
    """Strip configured database URLs/credentials from free text (e.g. exception messages)."""
    redacted = str(message)
    for url in (DATABASE_URL, SQLITE_FALLBACK_URL, _active_database_url):
        if not url or "://" not in url:
            continue
        # 1. Full URL forms first (works for credentials of any length).
        redacted = redacted.replace(url, _safe_db_url(url))
        userinfo, tail = _split_userinfo(url.split("://", 1)[1])
        secrets = []  # (token, must_be_standalone)
        if userinfo is not None:
            for form in {userinfo, unquote(userinfo)}:
                if form:
                    redacted = redacted.replace(f"://{form}@", "://***:***@")
            user, _, password = userinfo.partition(":")
            for form in (password, unquote(password)):
                if len(form) >= _MIN_FREE_TEXT_SECRET_LEN:
                    secrets.append((form, False))
            for form in (user, unquote(user)):
                if len(form) >= _MIN_FREE_TEXT_SECRET_LEN:
                    secrets.append((form, True))
        for match in _SENSITIVE_QUERY_PARAM_RE.finditer(tail):
            for form in (match.group(2), unquote(match.group(2))):
                if len(form) >= _MIN_FREE_TEXT_SECRET_LEN:
                    secrets.append((form, False))
        # 2. Free-text pass; longest first so a short secret that is a substring of a longer one
        #    cannot leave a fragment of the longer one behind.
        for token, standalone in sorted(set(secrets), key=lambda item: -len(item[0])):
            if standalone:
                redacted = _replace_standalone(redacted, token)
            else:
                redacted = redacted.replace(token, "***")
    return _mask_query_secrets(redacted)

# Lazy engine creation
_engine = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = _create_engine_for(_active_database_url)
    return _engine


def get_active_database_url() -> str:
    """Raw active URL (may contain credentials). Internal use only; never log or return it."""
    return _active_database_url


def get_database_status() -> dict:
    """Safe, non-sensitive database status fields suitable for the /health response."""
    return {
        "database_connected": check_db_connection(),
        "database_fallback_active": _fallback_active,
    }


def switch_to_sqlite_fallback(reason: str = ""):
    global _engine, _active_database_url, _fallback_active
    if _active_database_url.startswith("sqlite"):
        return

    previous_url = _active_database_url
    safe_reason = redact_db_secrets(reason)  # before the active URL changes
    _active_database_url = SQLITE_FALLBACK_URL
    _fallback_active = True

    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = _create_engine_for(_active_database_url)

    logger.warning(
        "Database fallback activated. previous_url=%s fallback_url=%s reason=%s",
        _safe_db_url(previous_url),
        _safe_db_url(_active_database_url),
        safe_reason,
    )

# For backwards compatibility (engine instance)
engine = get_engine()

# =====================================================
# SESSION
# =====================================================

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

Base = declarative_base()

# =====================================================
# FASTAPI DEPENDENCY
# =====================================================

def get_db():
    """
    FastAPI dependency.
    Transaction is controlled at service/repo layer.
    """
    SessionLocal.configure(bind=get_engine())
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =====================================================
# CONTEXT MANAGER (SCRIPT / CRON / INGEST)
# =====================================================

@contextmanager
def get_db_session():
    """
    Context manager with automatic commit/rollback.
    Use for scripts, jobs, batch ingestion.
    """
    SessionLocal.configure(bind=get_engine())
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# =====================================================
# DB INIT
# =====================================================

def init_db():
    """Create all tables"""
    # Ensure models are imported so metadata is populated
    from backend.database import models  # noqa: F401
    try:
        Base.metadata.create_all(bind=get_engine())
    except SQLAlchemyError as e:
        if DB_FALLBACK_TO_SQLITE and not get_active_database_url().startswith("sqlite"):
            switch_to_sqlite_fallback(reason=f"init_db failed: {type(e).__name__}: {e}")
            Base.metadata.create_all(bind=get_engine())
        else:
            raise

# --- init.sql statement splitting -------------------------------------------------------------

_DOLLAR_TAG_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")
_WORD_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
_TRIGGER_RE = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?TRIGGER\b", re.IGNORECASE
)
# duplicate_table, duplicate_object, duplicate_column, duplicate_schema. Deliberately excludes
# 23505 (unique_violation) and 42P16 (invalid_table_definition): those are real failures.
_PG_DUPLICATE_SQLSTATES = {"42P07", "42710", "42701", "42P06"}
_ALREADY_EXISTS_MESSAGE_RE = re.compile(
    r"\b(?:table|index|trigger|view|column|relation|sequence|schema|type|constraint)\s+"
    r"(?:\"[^\"]+\"|'[^']+'|\S+)\s+already exists\b",
    re.IGNORECASE,
)


def _split_sql_statements(script: str, dialect: str = "sqlite"):
    """Split an SQL script into individual, comment-free statements.

    * `-- line` and `/* block */` comments are dropped (never inside quoted text), so a statement
      that is preceded by a comment block is kept and a comment-only chunk yields nothing.
    * Semicolons inside '...' / "..." / `...` (and [...] on SQLite, $tag$...$tag$ on other
      dialects) do not terminate a statement.
    * CREATE [OR REPLACE] [TEMP] TRIGGER bodies (BEGIN ... END) may contain semicolons; the
      statement only ends at the `END` that closes the body (CASE ... END expressions inside it
      are accounted for, and a word that directly follows "." such as `NEW.end` is an identifier).

    Returned statements are stripped and have no trailing semicolon.

    Known limitations: an unquoted, unqualified column literally named `end` inside a trigger
    body is read as the end of the body; nested BEGIN ... END blocks (not valid SQLite trigger
    syntax) are not tracked; Postgres function bodies are only protected when $-quoted.
    """
    sqlite = dialect == "sqlite"
    statements = []
    buf = []
    n = len(script)
    i = 0

    # Per-statement trigger tracking.
    words = []          # first few keywords of the current statement (CREATE [OR REPLACE] [TEMP] TRIGGER)
    in_body = False     # inside BEGIN ... END of a trigger
    case_depth = 0
    last_was_end = False

    def reset_statement():
        nonlocal in_body, case_depth, last_was_end
        words.clear()
        in_body = False
        case_depth = 0
        last_was_end = False

    def flush():
        stmt = "".join(buf).strip()
        buf.clear()
        reset_statement()
        if stmt:
            statements.append(stmt)

    def is_trigger():
        return len(words) >= 2 and words[0] == "CREATE" and "TRIGGER" in words[1:4]

    def copy_quoted(start: int, quote: str, backslash_escapes: bool = False) -> int:
        """Copy a quoted run beginning at `start` (the opening quote) into buf; return next index."""
        j = start + 1
        while j < n:
            ch = script[j]
            if backslash_escapes and ch == "\\" and j + 1 < n:
                j += 2
                continue
            if ch == quote:
                if j + 1 < n and script[j + 1] == quote:  # doubled quote = escaped quote
                    j += 2
                    continue
                j += 1
                break
            j += 1
        else:
            j = n  # unterminated literal: take the rest
        buf.append(script[start:j])
        return j

    while i < n:
        c = script[i]
        nxt = script[i + 1] if i + 1 < n else ""

        if c == "-" and nxt == "-":  # line comment (keep the newline)
            end = script.find("\n", i)
            i = n if end == -1 else end
            continue
        if c == "/" and nxt == "*":  # block comment (nests on non-SQLite dialects)
            depth, j = 1, i + 2
            while j < n and depth:
                if script.startswith("*/", j):
                    depth -= 1
                    j += 2
                elif not sqlite and script.startswith("/*", j):
                    depth += 1
                    j += 2
                else:
                    j += 1
            buf.append(" ")
            i = j
            continue
        if c == "'":
            escapes = (not sqlite) and i > 0 and script[i - 1] in "Ee" and (
                i < 2 or script[i - 2] not in _WORD_CHARS
            )
            i = copy_quoted(i, "'", backslash_escapes=escapes)
            last_was_end = False
            continue
        if c == '"' or c == "`":
            i = copy_quoted(i, c)
            last_was_end = False
            continue
        if c == "[" and sqlite:
            end = script.find("]", i)
            j = n if end == -1 else end + 1
            buf.append(script[i:j])
            i = j
            last_was_end = False
            continue
        if c == "$" and not sqlite and (i == 0 or script[i - 1] not in _WORD_CHARS):
            m = _DOLLAR_TAG_RE.match(script, i)
            if m:
                tag = m.group(0)
                end = script.find(tag, m.end())
                j = n if end == -1 else end + len(tag)
                buf.append(script[i:j])
                i = j
                last_was_end = False
                continue
        if c in _WORD_CHARS and not c.isdigit():
            j = i
            while j < n and script[j] in _WORD_CHARS:
                j += 1
            word = script[i:j]
            upper = word.upper()
            buf.append(word)
            if len(words) < 4:
                words.append(upper)
            closes_body = False
            qualified = i > 0 and script[i - 1] == "."  # e.g. NEW.end is a column, not a keyword
            if is_trigger() and not qualified:
                if not in_body and upper == "BEGIN":
                    in_body = True
                    case_depth = 0
                elif in_body:
                    if upper == "CASE":
                        case_depth += 1
                    elif upper == "END":
                        if case_depth > 0:
                            case_depth -= 1  # END of a CASE expression, not of the body
                        else:
                            closes_body = True
            last_was_end = closes_body
            i = j
            continue
        if c == ";":
            if is_trigger() and in_body and not last_was_end:
                buf.append(c)  # semicolon inside the trigger body
            else:
                flush()
            i += 1
            continue

        buf.append(c)
        if not c.isspace():
            last_was_end = False
        i += 1

    flush()
    return statements


def _map_unquoted(statement: str, transform):
    """Apply `transform` to the parts of `statement` outside quotes ('...', "...", `...`, $tag$...$tag$)."""
    out = []
    plain_start = 0
    n = len(statement)
    i = 0
    while i < n:
        c = statement[i]
        end = None
        if c in "'\"`":
            escapes = (
                c == "'" and i > 0 and statement[i - 1] in "Ee"
                and (i < 2 or statement[i - 2] not in _WORD_CHARS)
            )
            j = i + 1
            while j < n:
                if escapes and statement[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if statement[j] == c:
                    if j + 1 < n and statement[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            end = min(j + 1, n)
        elif c == "$" and (i == 0 or statement[i - 1] not in _WORD_CHARS):
            m = _DOLLAR_TAG_RE.match(statement, i)
            if m:
                close = statement.find(m.group(0), m.end())
                end = n if close == -1 else close + len(m.group(0))
        if end is None:
            i += 1
            continue
        out.append(transform(statement[plain_start:i]))
        out.append(statement[i:end])
        plain_start = i = end
    out.append(transform(statement[plain_start:]))
    return "".join(out)


def _escape_percent_for_paramstyle(statement: str, paramstyle: str) -> str:
    """Escape literal "%" for DBAPIs with format/pyformat paramstyles (psycopg2, pymysql)."""
    if paramstyle in ("format", "pyformat"):
        return statement.replace("%", "%%")
    return statement


def _adapt_statement_for_dialect(statement: str, dialect: str):
    """Translate an init.sql statement for `dialect`; return None if it must be skipped.

    init.sql is written for SQLite. For other databases (Render/Postgres):
    * SQLite triggers are skipped (different syntax; `updated_at` is maintained by the ORM).
    * INTEGER PRIMARY KEY AUTOINCREMENT becomes BIGSERIAL PRIMARY KEY (outside string literals).
    * INSERT OR IGNORE INTO becomes INSERT INTO ... ON CONFLICT DO NOTHING.
    * INSERT OR REPLACE / REPLACE INTO / other INSERT OR <action> forms have no generic Postgres
      translation (an upsert needs a conflict target), so they are skipped with a warning.
    """
    if dialect == "sqlite":
        return statement
    if _TRIGGER_RE.match(statement):
        return None
    if re.match(r"^\s*(?:REPLACE\s+INTO\b|INSERT\s+OR\s+(?:REPLACE|ROLLBACK|ABORT|FAIL)\b)", statement, re.IGNORECASE):
        logger.warning(
            "Skipping init.sql statement not supported on %s (INSERT OR REPLACE-style): %s",
            dialect,
            redact_db_secrets(" ".join(statement.split())[:120]),
        )
        return None
    statement = _map_unquoted(
        statement,
        lambda seg: re.sub(
            r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", seg, flags=re.IGNORECASE
        ),
    )
    insert_or_ignore = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE)
    if insert_or_ignore.match(statement):
        statement = insert_or_ignore.sub("INSERT INTO", statement, count=1)
        unquoted = []
        _map_unquoted(statement, lambda seg: unquoted.append(seg) or seg)
        if not re.search(r"\bON\s+CONFLICT\b", " ".join(unquoted), flags=re.IGNORECASE):
            statement = statement.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return statement


def _error_sqlstate(exc: Exception):
    """SQLSTATE of a DBAPI error if the driver exposes one (psycopg2 pgcode, psycopg3 sqlstate)."""
    orig = getattr(exc, "orig", exc)
    for attr in ("pgcode", "sqlstate"):
        code = getattr(orig, attr, None)
        if code:
            return str(code)
    diag = getattr(orig, "diag", None)
    code = getattr(diag, "sqlstate", None)
    return str(code) if code else None


def _is_already_exists_error(exc: Exception) -> bool:
    """True for "object already exists" failures, which are harmless when re-running init.sql.

    When the driver reports a SQLSTATE it alone decides (so a unique violation, whose message
    also says "already exists", stays a real failure). Without one, a specific message shape
    such as "table x already exists" / "duplicate column name" is required.
    """
    code = _error_sqlstate(exc)
    if code is not None:
        return code in _PG_DUPLICATE_SQLSTATES
    orig = getattr(exc, "orig", None)
    message = str(orig if orig is not None else exc)
    lowered = message.lower()
    if "violates" in lowered or "key (" in lowered or "constraint failed" in lowered:
        return False
    return bool(_ALREADY_EXISTS_MESSAGE_RE.search(message)) or "duplicate column name" in lowered


def run_init_sql(engine=None, sql_path=None):
    """Run init.sql to create tables that might not be in ORM (like user_profiles).

    Every statement is executed independently: a failure is logged (with secrets redacted) and
    never aborts startup or the remaining statements. "Already exists" outcomes are logged at
    INFO, real failures at ERROR. Returns a summary dict (executed / already_exists / failed /
    skipped counts).

    `engine` and `sql_path` default to the application's engine and the bundled init.sql; they
    exist so the script can be applied to an isolated database.
    """
    summary = {"executed": 0, "already_exists": 0, "failed": 0, "skipped": 0}
    init_sql_path = sql_path or os.path.join(os.path.dirname(__file__), "init.sql")
    if not os.path.exists(init_sql_path):
        logger.warning("init.sql not found at %s; skipping.", init_sql_path)
        return summary

    logger.info("Running init.sql from %s...", init_sql_path)
    with open(init_sql_path, "r", encoding="utf-8") as f:
        sql_script = f.read()

    engine = engine or get_engine()
    dialect = engine.dialect.name.lower()

    with engine.connect() as connection:
        for raw_statement in _split_sql_statements(sql_script, dialect):
            statement = _adapt_statement_for_dialect(raw_statement, dialect)
            if statement is None:
                summary["skipped"] += 1
                continue
            try:
                # exec_driver_sql: init.sql is literal SQL, so ":name" inside it must not be
                # treated as a bind parameter; "%" is escaped for format/pyformat drivers.
                connection.exec_driver_sql(
                    _escape_percent_for_paramstyle(statement, engine.dialect.paramstyle)
                )
                connection.commit()
                summary["executed"] += 1
            except Exception as e:
                # Critical: reset failed transaction so subsequent statements can run.
                connection.rollback()
                reason = redact_db_secrets(str(getattr(e, "orig", None) or e))
                snippet = redact_db_secrets(" ".join(statement.split())[:200])
                if _is_already_exists_error(e):
                    summary["already_exists"] += 1
                    logger.info("init.sql statement already applied: %s [SQL: %s]", reason, snippet)
                else:
                    summary["failed"] += 1
                    logger.error("init.sql statement failed: %s [SQL: %s]", reason, snippet)

    if summary["failed"]:
        logger.warning(
            "init.sql finished with %d failed statement(s) (%d executed, %d already existed).",
            summary["failed"], summary["executed"], summary["already_exists"],
        )
    else:
        logger.info(
            "init.sql executed successfully (%d executed, %d already existed, %d skipped).",
            summary["executed"], summary["already_exists"], summary["skipped"],
        )
    return summary


# =====================================================
# HEALTH CHECK
# =====================================================

def check_db_connection() -> bool:
    """Verify DB connectivity"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(
            "Database connection failed (%s): %s: %s",
            _safe_db_url(get_active_database_url()),
            type(e).__name__,
            redact_db_secrets(str(e)),
        )
        return False
