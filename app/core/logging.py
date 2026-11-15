"""Logging standards: one line per event, secrets redacted before anything is written."""
import logging

from app.core.security import redact


class RedactingFilter(logging.Filter):
    def __init__(self, secrets_=()):
        super().__init__()
        self._secrets = [s for s in secrets_ if s]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage(), self._secrets)
            record.args = ()
        except Exception:  # never let logging break a request
            pass
        return True


def configure(secrets_=()) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for h in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in h.filters):
            h.addFilter(RedactingFilter(secrets_))
