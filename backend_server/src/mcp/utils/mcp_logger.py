"""
MCP Tools Logger

File-based logger for MCP tools running inside gunicorn+gevent workers.
print() from request handlers doesn't reliably reach systemd journal due to
gunicorn's capture_output=True + gevent stdout pipe buffering.

Usage:
    from ..utils.mcp_logger import get_mcp_logger
    logger = get_mcp_logger()
    logger.info("message")
    logger.error("error message")

Log file: /tmp/virtualpytest/mcp.log (rotated at 5MB, 3 backups)
"""

import os
import logging
from logging.handlers import RotatingFileHandler

_logger = None

LOG_DIR = '/tmp/virtualpytest'
LOG_FILE = os.path.join(LOG_DIR, 'mcp.log')
MAX_BYTES = 5 * 1024 * 1024  # 5MB
BACKUP_COUNT = 3


def get_mcp_logger() -> logging.Logger:
    """Get or create the MCP file logger."""
    global _logger
    if _logger is not None:
        return _logger

    os.makedirs(LOG_DIR, exist_ok=True)

    _logger = logging.getLogger('mcp_tools')
    _logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on reload
    if not _logger.handlers:
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT
        )
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        _logger.addHandler(handler)

    return _logger
