import logging
from pathlib import Path


def setup_logger(log_level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    logger = logging.getLogger("paper_watcher")
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger
