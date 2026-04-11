"""
config/settings.py
 
Central configuration module.
All environment variables are validated and typed here.
No other module should call os.environ directly.
 
Deployment behavior:
- Local execution (RENDER not set) — Meta variables are optional.
  App starts without META_APP_SECRET, META_APP_ID, PAGE_ACCESS_TOKEN,
  and VERIFY_TOKEN to allow local runs without a Meta Developer account.
  HMAC verification still executes — it fails gracefully when no real
  webhook traffic arrives. All other required variables still apply.
- Render deployment (RENDER set) — all variables are required.
  Server aborts with a clear error if any required variable is missing.
 
Note: Production detection is deployment-bound, not flag-controlled.
RENDER is set automatically by Render's infrastructure and is not
a user-controlled value in normal operation.
"""
 
import os
from dataclasses import dataclass
from dotenv import load_dotenv
 
load_dotenv()
 
 
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
    # Required on Render. Optional in local execution — allows runs
    # without a Meta Developer account. HMAC verification still executes.
    meta_app_secret:   str
    meta_app_id:       str
    page_access_token: str
    verify_token:      str
 
    # ── Pinecone ──
    pinecone_api_key: str
    pinecone_index:   str
 
    # ── Rate limits ──
    rate_limit:        str
    msg_gap_secs:      int
    spam_window_secs:  int
    spam_max_msgs:     int
    email_window_secs: int
    email_max:         int
 
    # ── TTLs ──
    dedup_ttl:   int
    session_ttl: int
 
    # ── Flask ──
    # Used only for Flask-specific behavior (rate limiter storage URI).
    # Not used as a security decision source.
    port:          int
    flask_env:     str
    is_production: bool
 
 
def _require(key: str) -> str:
    """Fetch a required env var or raise a clear error."""
    value = os.getenv(key, "").strip()
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {key}\n"
            f"Add it to your .env file or Render environment settings."
        )
    return value
 
 
def _optional(key: str) -> str:
    """
    Fetch an optional env var.
    Returns empty string if not set — caller must handle the empty case.
    """
    return os.getenv(key, "").strip()
 
 
def load_settings() -> Settings:
    """
    Load and validate all environment variables.
    Called once at application startup.
 
    Deployment context is inferred from the RENDER environment variable,
    which is set automatically by Render's infrastructure. This is a
    deployment-bound guarantee, not a hard invariant — it is the correct
    tradeoff for a single-platform, single-developer system.
 
    Meta variables are required on Render and optional in local execution.
    All other required variables must be set in both contexts.
 
    Raises:
        EnvironmentError: If any required variable is missing.
    """
    # ── Deployment context — single source of truth ──
    # is_production: True when running on Render infrastructure.
    # is_local:      True when running on any non-Render machine.
    is_production = bool(os.getenv("RENDER"))
    is_local      = not is_production
 
    # ── Meta vars — required on Render, optional locally ──
    meta_resolver = _optional if is_local else _require
 
    return Settings(
        # Required in all contexts
        gemini_api_key    = _require("GEMINI_API_KEY"),
        mysql_uri         = _require("MYSQL_URI"),
        redis_url         = _require("REDIS_URL").replace('"', '').replace("'", ""),
        sendgrid_api_key  = _require("SENDGRID_API_KEY"),
        admin_email       = _require("ADMIN_EMAIL"),
 
        # Required on Render, optional locally
        meta_app_secret   = meta_resolver("META_APP_SECRET"),
        meta_app_id       = meta_resolver("META_APP_ID"),
        page_access_token = meta_resolver("PAGE_ACCESS_TOKEN"),
        verify_token      = meta_resolver("VERIFY_TOKEN"),
 
        # Optional with defaults
        pinecone_api_key  = _optional("PINECONE_API_KEY"),
        pinecone_index    = _optional("PINECONE_INDEX"),
 
        rate_limit        = os.getenv("RATE_LIMIT",        "30 per minute"),
        msg_gap_secs      = int(os.getenv("MSG_GAP_SECS",      "5")),
        spam_window_secs  = int(os.getenv("SPAM_WINDOW_SECS",  "20")),
        spam_max_msgs     = int(os.getenv("SPAM_MAX_MSGS",     "10")),
        email_window_secs = int(os.getenv("EMAIL_WINDOW_SECS", "3600")),
        email_max         = int(os.getenv("EMAIL_MAX",         "3")),
        dedup_ttl         = int(os.getenv("DEDUP_TTL_SECS",    "300")),
        session_ttl       = int(os.getenv("SESSION_TTL_SECS",  str(60 * 60 * 24 * 90))),
        port              = int(os.getenv("PORT",              "5001")),
        flask_env         = os.getenv("FLASK_ENV", "production"),
        is_production     = is_production,
    )
 
 
# ── Singleton — imported by all modules ──
settings = load_settings()
 