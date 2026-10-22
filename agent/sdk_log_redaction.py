"""Scrub SDK-owned handlers before their output reaches stdout/journal."""
import logging
import re
from agent.redact import redact_for_egress


def scrub_sdk_text(text):
    text = redact_for_egress(text)
    # Websocket connection URLs are ephemeral credentials; no query value is needed in logs.
    return re.sub(r'(wss?://[^\s?]+)\?[^\s]+', r'\1?[redacted]', text)


class SDKRedactingFormatter(logging.Formatter):
    def __init__(self, original):
        super().__init__()
        self.original = original or logging.Formatter()

    def format(self, record):
        try:
            return scrub_sdk_text(self.original.format(record))
        except Exception:
            return '[SDK log redaction unavailable]'


def protect_sdk_logger(logger):
    if not any(isinstance(f, SDKRedactingFilter) for f in logger.filters):
        logger.addFilter(SDKRedactingFilter())
    for handler in logger.handlers:
        if not isinstance(handler.formatter, SDKRedactingFormatter):
            handler.setFormatter(SDKRedactingFormatter(handler.formatter))


class SDKRedactingFilter(logging.Filter):
    def filter(self, record):
        record.msg, record.args = scrub_sdk_text(record.getMessage()), ()
        if record.exc_info:
            record.exc_text = scrub_sdk_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True
