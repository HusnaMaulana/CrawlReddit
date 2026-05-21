"""
logging_config.py — Centralized logging setup for the crawl pipeline.

Usage
─────
    from Utils.logging_config import setup_logging, get_logger

    setup_logging()                         # call once at process start
    log = get_logger()                      # retrieve logger anywhere
    log.info("Starting crawl...")
    log.warning("Rate limited, retrying...")
    log.error("Failed to fetch post: ...")

The root logger name is "crawl_pipeline".
Child loggers (e.g. "crawl_pipeline.posts") inherit its handlers.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# ── ANSI color codes ──────────────────────────────────────────

_COLORS: dict[str, str] = {
    "DEBUG": "\033[36m",  # cyan
    "INFO": "\033[32m",  # green
    "WARNING": "\033[33m",  # yellow
    "ERROR": "\033[31m",  # red
    "CRITICAL": "\033[35m",  # magenta
    "RESET": "\033[0m",
}

ROOT_LOGGER = "crawl_pipeline"


# ── colored console formatter ─────────────────────────────────


class _ColorFormatter(logging.Formatter):
    """Inject ANSI color codes around the level name for console output."""

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelname, _COLORS["RESET"])
        reset = _COLORS["RESET"]
        # pad level name for alignment
        record.levelname = f"{color}{record.levelname:<8}{reset}"
        return super().format(record)


# ── public API ────────────────────────────────────────────────


def setup_logging(
    log_file: str = "DataOutput/crawl.log",
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB per file
    backup_count: int = 5,
) -> logging.Logger:
    """
    Configure the pipeline logger.  Safe to call multiple times —
    additional calls are no-ops if handlers are already attached.

    Parameters
    ──────────
    log_file     : Path for the rotating log file.
    level        : Minimum log level (default INFO).
    max_bytes    : Rotate file when it reaches this size.
    backup_count : Number of rotated backups to keep.
    """
    logger = logging.getLogger(ROOT_LOGGER)

    # Idempotent — skip if already configured
    if logger.handlers:
        return logger

    logger.setLevel(level)

    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

    # ── file handler (plain text, rotated) ────────────────────
    file_fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    fh.setFormatter(file_fmt)
    fh.setLevel(level)

    # ── console handler (colored) ─────────────────────────────
    console_fmt = _ColorFormatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ch = logging.StreamHandler()
    ch.setFormatter(console_fmt)
    ch.setLevel(level)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Retrieve a logger under the pipeline namespace.

    get_logger()          → logging.getLogger("crawl_pipeline")
    get_logger("posts")   → logging.getLogger("crawl_pipeline.posts")
    """
    if name:
        return logging.getLogger(f"{ROOT_LOGGER}.{name}")
    return logging.getLogger(ROOT_LOGGER)
