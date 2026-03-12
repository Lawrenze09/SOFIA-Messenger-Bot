"""
database/models.py

Database schema management.
Creates all tables on first startup if they don't exist.
"""

from database.client import get_connection
from utils.logger import get_logger

logger = get_logger(__name__)

_CREATE_SESSIONS = """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id VARCHAR(64) PRIMARY KEY,
        user_id    VARCHAR(64) NOT NULL,
        started_at DATETIME    NOT NULL,
        last_seen  DATETIME    NOT NULL,
        state      VARCHAR(16) NOT NULL DEFAULT 'BOT_ACTIVE',
        INDEX idx_user (user_id)
    )
"""

_CREATE_MESSAGES = """
    CREATE TABLE IF NOT EXISTS messages (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        session_id    VARCHAR(64) NOT NULL,
        user_id       VARCHAR(64) NOT NULL,
        message       TEXT        NOT NULL,
        response      TEXT,
        intent        VARCHAR(32) NOT NULL,
        timestamp     DATETIME    NOT NULL,
        response_time FLOAT,
        INDEX idx_user    (user_id),
        INDEX idx_session (session_id),
        INDEX idx_time    (timestamp)
    )
"""

_CREATE_INTENT_LOG = """
    CREATE TABLE IF NOT EXISTS intent_log (
        id         BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id    VARCHAR(64) NOT NULL,
        session_id VARCHAR(64) NOT NULL,
        intent     VARCHAR(32) NOT NULL,
        message    TEXT        NOT NULL,
        timestamp  DATETIME    NOT NULL,
        INDEX idx_intent (intent),
        INDEX idx_time   (timestamp)
    )
"""


def init_tables() -> None:
    """
    Create all required tables if they do not exist.
    Called once at application startup.

    Raises:
        Exception: Re-raised if table creation fails so startup aborts visibly.
    """
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        for ddl in (_CREATE_SESSIONS, _CREATE_MESSAGES, _CREATE_INTENT_LOG):
            cursor.execute(ddl)
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("Database tables verified.")
    except Exception as exc:
        logger.error(f"Database init failed: {exc}")
        raise
