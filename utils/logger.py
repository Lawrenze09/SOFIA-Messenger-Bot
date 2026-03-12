"""
utils/logger.py

Centralized structured logging setup.
All modules import get_logger() from here.
"""

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Returns a named logger with consistent formatting.

    Args:
        name: Module name — use __name__ when calling.

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    return logger
