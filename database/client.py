"""
database/client.py

PyMySQL connection factory.
Parses TiDB URI format including SSL certificate configuration.
"""

import re
from urllib.parse import urlparse, unquote, parse_qs

import pymysql
import pymysql.cursors

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def _parse_config() -> dict:
    """
    Parse MYSQL_URI into a pymysql-compatible connection dict.
    Handles TiDB URI format with SSL parameters in query string.

    Returns:
        Dictionary of pymysql.connect() keyword arguments.
    """
    uri    = re.sub(r"^mysql\+\w+://", "mysql://", settings.mysql_uri)
    parsed = urlparse(uri)
    query  = parse_qs(parsed.query)
    ssl_ca = unquote(query.get("ssl_ca", [""])[0])

    config: dict = {
        "host"           : parsed.hostname,
        "port"           : parsed.port or 4000,
        "user"           : parsed.username,
        "password"       : parsed.password,
        "database"       : parsed.path.lstrip("/"),
        "connect_timeout": 10,
        "cursorclass"    : pymysql.cursors.DictCursor,
    }

    if ssl_ca:
        import os
        if os.path.exists(ssl_ca):
            config["ssl"] = {"ca": ssl_ca}
        else:
            logger.warning(f"SSL CA certificate not found at: '{ssl_ca}'")

    return config


def get_connection() -> pymysql.connections.Connection:
    """
    Create and return a new database connection.
    Caller is responsible for closing the connection.

    Returns:
        Active pymysql Connection.

    Raises:
        pymysql.Error: If connection fails.
    """
    return pymysql.connect(**_parse_config())
