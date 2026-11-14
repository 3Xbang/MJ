from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _logger

# Derive log directory relative to this file so it works on any machine/OS.
_log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)

_logger.remove()
_logger.add(
    sys.stderr,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
)
_logger.add(
    _log_dir / "app.log",
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    compression="zip",
)


def get_logger(name: str):
    """Get a bound logger for the given module name."""
    return _logger.bind(name=name)


logger = get_logger("ai_film_editor_nodes")
