"""
Auto-migration module for Fors8 PostgreSQL schema.

Creates all required tables and indexes if they don't exist.
Safe to call multiple times (all statements use IF NOT EXISTS).
"""

import logging
import os

logger = logging.getLogger('fors8.db_migrate')

# ---------------------------------------------------------------------------
# SQL: table definitions
# ---------------------------------------------------------------------------

_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    prediction_id   TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS predictions (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT REFERENCES conversations(id),
    question         TEXT,
    status           TEXT DEFAULT 'queued',
    progress_pct     INT DEFAULT 0,
    progress_message TEXT,
    model_name       TEXT,
    num_agents       INT,
    num_runs         INT,
    outcomes         JSONB,
    actor_results    JSONB,
    answers          JSONB,
    data             JSONB,
    gpu_cost         DECIMAL(10,4) DEFAULT 0,
    error            TEXT,
    created_at       TIMESTAMP DEFAULT NOW(),
    completed_at     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_memories (
    id                    TEXT PRIMARY KEY,
    actor_id              TEXT,
    memory_type           TEXT DEFAULT 'insight',
    content               TEXT,
    source_prediction_id  TEXT REFERENCES predictions(id),
    round_num             INT,
    created_at            TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_settings (
    id          SERIAL PRIMARY KEY,
    key         TEXT UNIQUE,
    value       TEXT,
    updated_at  TIMESTAMP DEFAULT NOW()
);
"""

_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages(conversation_id);

CREATE INDEX IF NOT EXISTS idx_messages_prediction_id
    ON messages(prediction_id);

CREATE INDEX IF NOT EXISTS idx_predictions_conversation_id
    ON predictions(conversation_id);

CREATE INDEX IF NOT EXISTS idx_predictions_status
    ON predictions(status);

CREATE INDEX IF NOT EXISTS idx_agent_memories_actor_id
    ON agent_memories(actor_id);

CREATE INDEX IF NOT EXISTS idx_agent_memories_source_prediction
    ON agent_memories(source_prediction_id);

CREATE INDEX IF NOT EXISTS idx_user_settings_key
    ON user_settings(key);
"""


def _try_create_database(database_url: str) -> None:
    """Attempt to CREATE DATABASE fors8 if it doesn't already exist.

    Connects to the default ``postgres`` database first, checks for the
    target database, and creates it when missing.  Failures are logged
    but never raised.
    """
    try:
        import psycopg2
    except ImportError:
        return

    # Derive the target database name from the DSN
    db_name = 'fors8'
    if 'dbname=' in database_url:
        for part in database_url.split():
            if part.startswith('dbname='):
                db_name = part.split('=', 1)[1]
                break

    # Build a DSN that points at the default 'postgres' database
    if 'dbname=' in database_url:
        admin_dsn = database_url.replace(f'dbname={db_name}', 'dbname=postgres')
    else:
        admin_dsn = 'dbname=postgres host=localhost'

    try:
        conn = psycopg2.connect(admin_dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
        )
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{db_name}"')
            logger.info("Created database '%s'", db_name)
        else:
            logger.debug("Database '%s' already exists", db_name)
        cur.close()
        conn.close()
    except Exception as exc:
        logger.debug("Could not auto-create database '%s': %s", db_name, exc)


def _add_column_if_missing(cur, table: str, column: str, col_type: str) -> None:
    """Add a column to an existing table if it doesn't already exist."""
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            (table, column),
        )
        if cur.fetchone() is None:
            cur.execute(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
            logger.info("Added column %s.%s (%s)", table, column, col_type)
        else:
            logger.debug("Column %s.%s already exists", table, column)
    except Exception as exc:
        logger.warning("Failed to add column %s.%s: %s", table, column, exc)


def ensure_schema(database_url: str = None) -> None:
    """Create all tables and indexes if they don't exist.

    Safe to call on every application startup.  If PostgreSQL is
    unavailable or psycopg2 is not installed, failures are logged and
    the function returns silently.
    """
    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 not installed -- skipping schema migration")
        return

    if database_url is None:
        database_url = os.environ.get(
            'DATABASE_URL', 'dbname=fors8 host=localhost'
        )

    # Step 1: try to create the database itself
    _try_create_database(database_url)

    # Step 2: connect to the target database and run DDL
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute(_TABLES_SQL)
        cur.execute(_INDEXES_SQL)

        # Incremental migrations: add columns that may not exist yet
        _add_column_if_missing(cur, 'predictions', 'graph_id', 'TEXT')
        _add_column_if_missing(cur, 'predictions', 'social_results', 'JSONB')
        _add_column_if_missing(cur, 'predictions', 'agent_decisions', 'JSONB')
        _add_column_if_missing(cur, 'predictions', 'grounding_score', 'FLOAT')
        _add_column_if_missing(cur, 'predictions', 'grounding_report', 'JSONB')
        _add_column_if_missing(cur, 'predictions', 'scenario_type', 'TEXT')

        cur.close()
        conn.close()
        logger.info("Database schema is up to date")
    except Exception as exc:
        logger.warning("Schema migration skipped (PostgreSQL unavailable): %s", exc)
