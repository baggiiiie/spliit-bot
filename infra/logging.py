from __future__ import annotations

import logging


def configure_logging() -> logging.Logger:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    # httpx logs full request URLs at INFO level, which can expose Telegram bot tokens.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return logging.getLogger("config")


logger = configure_logging()
