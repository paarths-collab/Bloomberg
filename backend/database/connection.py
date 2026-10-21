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

def run_init_sql():
    """Run init.sql to create tables that might not be in ORM (like user_profiles)"""
    init_sql_path = os.path.join(os.path.dirname(__file__), "init.sql")
    if os.path.exists(init_sql_path):
        logger.info("Running init.sql from %s...", init_sql_path)
        with open(init_sql_path, "r") as f:
            sql_script = f.read()

        dialect = get_engine().dialect.name.lower()

        def _split_sql_statements(script: str):
            statements = []
            current_statement = []
            in_trigger_block = False

            for line in script.split('\n'):
                stripped = line.strip()
                current_statement.append(line)

                if 'CREATE TRIGGER' in stripped.upper():
                    in_trigger_block = True

                if in_trigger_block and stripped.upper() == 'END;':
                    statements.append('\n'.join(current_statement))
                    current_statement = []
                    in_trigger_block = False
                elif not in_trigger_block and stripped.endswith(';'):
                    statements.append('\n'.join(current_statement))
                    current_statement = []

            if current_statement:
                stmt = '\n'.join(current_statement).strip()
                if stmt:
                    statements.append(stmt)

            return statements

        # Normalize SQLite-only syntax for non-SQLite databases (Render/Postgres).
        if dialect != "sqlite":
            sql_script = re.sub(
                r"CREATE\s+TRIGGER[\s\S]*?END;",
                "",
                sql_script,
                flags=re.IGNORECASE,
            )
            sql_script = re.sub(
                r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
                "BIGSERIAL PRIMARY KEY",
                sql_script,
                flags=re.IGNORECASE,
            )
            sql_script = re.sub(
                r"INSERT\s+OR\s+IGNORE\s+INTO",
                "INSERT INTO",
                sql_script,
                flags=re.IGNORECASE,
            )
            sql_script = re.sub(
                r"\);\s*(?=\s*--\s*SQLite trigger|\s*$)",
                ") ON CONFLICT DO NOTHING;",
                sql_script,
                flags=re.IGNORECASE,
            )

        statements = _split_sql_statements(sql_script)

        with get_engine().connect() as connection:
            for statement in statements:
                statement = statement.strip()
                if not statement or statement.startswith('--'):
                    continue
                try:
                    connection.execute(text(statement))
                    connection.commit()
                except Exception as e:
                    # Critical: reset failed transaction so subsequent statements can run.
                    connection.rollback()
                    logger.warning(
                        "Warning executing statement: %s [SQL: %s]",
                        redact_db_secrets(str(e)),
                        statement[:200],
                    )

        logger.info("init.sql executed successfully.")

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
