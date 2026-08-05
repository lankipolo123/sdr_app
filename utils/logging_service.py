import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(log_folder: str = "logs", name: str = "sdr_controller") -> logging.Logger:
    os.makedirs(log_folder, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:  # avoid duplicate handlers on repeated setup calls
        file_handler = RotatingFileHandler(
            os.path.join(log_folder, "sdr_controller.log"),
            maxBytes=1_000_000,
            backupCount=3,
        )
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def clear_log(logger: logging.Logger):
    """Truncates the log file in place instead of deleting it, so the
    handler keeps writing to the same still-open file descriptor rather
    than a stale/deleted one. Goes through the handler's own lock
    (acquire/release) since the logger can be written to from other
    threads (e.g. SerialThread) at any moment."""
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            handler.acquire()
            try:
                handler.stream.close()
                handler.stream = open(handler.baseFilename, "w")
            finally:
                handler.release()
