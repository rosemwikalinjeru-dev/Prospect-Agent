"""Loguru configuration: consistent structured logging across the whole pipeline."""

import sys

from loguru import logger


def configure_logging(level: str = "INFO") -> None:
    """Reset loguru's default handler and reconfigure with our preferred format/level.

    Call once, early, from the CLI entrypoint — not from library modules, so importing
    a module never has the side effect of reconfiguring global logging.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
        backtrace=False,
        diagnose=False,
    )
