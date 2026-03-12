"""
gunicorn.conf.py

Production Gunicorn configuration.
Tuned for Render free tier (512MB RAM).
"""

import os

# ── Workers ──
workers     = 2
worker_class = "sync"
threads     = 2
timeout     = 120
keepalive   = 5

# ── Binding ──
port = os.getenv("PORT", "5001")
bind = f"0.0.0.0:{port}"

# ── Logging ──
loglevel    = "info"
accesslog   = "-"
errorlog    = "-"

# ── Startup hook — runs once per worker after fork ──
def post_fork(server, worker):
    """
    Re-initialize services in each Gunicorn worker after fork.
    Prevents shared Redis/MySQL connections from being reused
    across worker processes (causes silent failures on Windows/Linux).
    """
    from app.main import startup
    startup()
