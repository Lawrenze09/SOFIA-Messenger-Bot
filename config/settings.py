"""
config/settings.py

Central configuration module.
All environment variables are validated and typed here.
No other module should call os.environ directly.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(override=os.getenv("FLASK_ENV") == "development")


@dataclass(frozen=True)
class Settings:
    # ── Gemini ──
    gemini_api_key: str

    # ── Database ──
    mysql_uri: str

    # ── Cache / Session ──
    redis_url: str

    # ── Notifications ──
    sendgrid_api_key: str
    admin_email: str

    # ── Facebook Messenger ──
    meta_app_secret: str
    page_access_token: str
    verify_token: str

    # ── Pinecone ──
    pinecone_api_key: str
    pinecone_index: str

    # ── Rate limits ──
    rate_limit: str
    msg_gap_secs: int
    spam_window_secs: int
    spam_max_msgs: int
    email_window_secs: int
    email_max: int

    # ── TTLs ──
    dedup_ttl: int
    session_ttl: int

    # ── Flask ──
    port: int
    flask_env: str


def _require(key: str) -> str:
    """Fetch a required env var or raise a clear error."""
    value = os.getenv(key, "").strip()
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {key}\n"
            f"Add it to your .env file or Render environment settings."
        )
    return value


def load_settings() -> Settings:
    """
    Load and validate all environment variables.
    Called once at application startup.
    Raises EnvironmentError if any required variable is missing.
    """
    return Settings(
        # Required
        gemini_api_key    = _require("GEMINI_API_KEY"),
        mysql_uri         = _require("MYSQL_URI"),
        redis_url         = _require("REDIS_URL").replace('"', '').replace("'", ""),
        sendgrid_api_key  = _require("SENDGRID_API_KEY"),
        admin_email       = _require("ADMIN_EMAIL"),
        meta_app_secret   = _require("META_APP_SECRET"),
        page_access_token = _require("PAGE_ACCESS_TOKEN"),
        verify_token      = _require("VERIFY_TOKEN"),

        # Optional with defaults
        pinecone_api_key  = os.getenv("PINECONE_API_KEY", ""),
        pinecone_index    = os.getenv("PINECONE_INDEX", ""),

        rate_limit        = os.getenv("RATE_LIMIT",        "30 per minute"),
        msg_gap_secs      = int(os.getenv("MSG_GAP_SECS",      "5")),
        spam_window_secs  = int(os.getenv("SPAM_WINDOW_SECS",  "20")),
        spam_max_msgs     = int(os.getenv("SPAM_MAX_MSGS",     "10")),
        email_window_secs = int(os.getenv("EMAIL_WINDOW_SECS", "1800")),
        email_max         = int(os.getenv("EMAIL_MAX",         "2")),
        dedup_ttl         = int(os.getenv("DEDUP_TTL_SECS",    "300")),
        session_ttl       = int(os.getenv("SESSION_TTL_SECS",  str(60 * 60 * 24 * 90))),
        port              = int(os.getenv("PORT",              "5001")),
        flask_env         = os.getenv("FLASK_ENV", "production"),
    )


# ── Singleton — imported by all modules ──
settings = load_settings()
