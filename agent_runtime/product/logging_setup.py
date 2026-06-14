from __future__ import annotations

import os

from utils.logger import setup_logging


def setup_demo_logging() -> None:
    """Configure a basic logger for demo scripts."""

    level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(name="demo", level=level)
