"""
app/main.py

Flask application factory and startup sequence.
Initializes all services before accepting traffic.
"""

import os

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app.routes import router
from config import settings
from database.models import init_tables
from services.session_service import get_redis
from utils.logger import get_logger

logger = get_logger(__name__)


def create_app() -> Flask:
    """
    Flask application factory.
    Creates and configures the Flask app with rate limiting and routes.

    Returns:
        Configured Flask application instance.
    """
    app = Flask(__name__)

    # ── Rate limiter ──
    Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=[settings.rate_limit],
        storage_uri=(
            settings.redis_url
            if settings.flask_env != "development"
            else "memory://"
        ),
    )

    # ── Register routes ──
    app.register_blueprint(router)

    return app


def startup() -> None:
    """
    Run all startup checks before the app accepts traffic.
    Aborts with a clear error if any critical service is unavailable.
    """
    logger.info("Sofia v2 starting up...")

    # ── Database ──
    init_tables()

    # ── Redis ──
    try:
        get_redis().ping()
        logger.info("Redis connected.")
    except Exception as exc:
        logger.error(f"Redis connection failed: {exc}")
        raise

    logger.info("Sofia v2 ready.")


# ── Gunicorn post_fork hook — runs startup in each worker ──
def post_fork(server, worker):
    startup()


# ── Local development entry point ──
if __name__ == "__main__":
    try:
        startup()
    except Exception as exc:
        import traceback
        print(f"\nSTARTUP FAILED: {exc}\n")
        traceback.print_exc()
        raise

    app = create_app()
    print("\n✓ Sofia is starting the Flask server...\n")
    app.run(
        host="0.0.0.0",
        port=settings.port,
        debug=settings.flask_env == "development",
        use_reloader=False,
    )
