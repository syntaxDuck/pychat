import os
import logging
from datetime import datetime


def setup_logging(
    logger_name,
    logger_level=logging.INFO,
    file_handler_level=logging.DEBUG,
    console_handler_level=logging.ERROR,
    log_file=None,
    log_dir="logs",
    log_timestamp=True,
    file_mode="a",
    encoding="utf-8",
) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(
        log_dir,
        (
            logger_name
            if log_file is None
            else log_file
            + (f'_{datetime.now().strftime("%Y%m%d_%H%M%S")}' if log_timestamp else "")
            + ".log"
        ),
    )

    logger = logging.getLogger(logger_name)
    logger.setLevel(logger_level)

    if not logger.hasHandlers():
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler = logging.FileHandler(log_file, mode=file_mode, encoding=encoding)
        file_handler.setLevel(file_handler_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_handler_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
