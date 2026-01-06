import os
import logging
from datetime import datetime
from typing import Optional


def setup_logging(
    logger_name: str,
    logger_level: int = logging.INFO,
    file_handler_level: int = logging.DEBUG,
    console_handler_level: int = logging.ERROR,
    log_dir: str = "logs",
    log_file_name: Optional[str] = None,
    add_timestamp_to_log_file: bool = True,
    file_mode: str = "a",
    encoding: str = "utf-8",
    force_reconfig: bool = False,
) -> logging.Logger:
    """
    Set up a logger with file and console handlers.

    Args:
        logger_name: Name of the logger.
        logger_level: Logging level for the logger.
        file_handler_level: Logging level for the file handler.
        console_handler_level: Logging level for the console handler.
        log_dir: Directory to store log files.
        log_file_name: Name of the log file. If None, defaults to `logger_name`.log.
        add_timestamp_to_log_file: Whether to add a timestamp to the log file name.
        file_mode: File mode for the file handler.
        encoding: Encoding for the file handler.
        force_reconfig: If True, remove existing handlers and reconfigure.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(logger_level)

    if force_reconfig and logger.hasHandlers():
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()

    if not logger.hasHandlers():
        os.makedirs(log_dir, exist_ok=True)

        if log_file_name is None:
            log_file_name = f"{logger_name}.log"

        if add_timestamp_to_log_file:
            base, ext = os.path.splitext(log_file_name)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file_path = os.path.join(log_dir, f"{base}_{timestamp}{ext}")
        else:
            log_file_path = os.path.join(log_dir, log_file_name)

        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        # File Handler
        file_handler = logging.FileHandler(
            log_file_path, mode=file_mode, encoding=encoding
        )
        file_handler.setLevel(file_handler_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_handler_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger