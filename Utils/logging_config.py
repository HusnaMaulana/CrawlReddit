import logging
import os
from logging.handlers import RotatingFileHandler

_COLORS: dict[str, str] = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
    "RESET": "\033[0m",
}

ROOT_LOGGER = "crawl_pipeline"

class _ColorFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelname, _COLORS["RESET"])
        reset = _COLORS["RESET"]
        record.levelname = f"{color}{record.levelname:<8}{reset}"
        return super().format(record)

def setup_logging(
    log_file: str = "DataOutput/crawl.log",
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    
    logger = logging.getLogger(ROOT_LOGGER)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

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

    if name:
        return logging.getLogger(f"{ROOT_LOGGER}.{name}")
    return logging.getLogger(ROOT_LOGGER)
