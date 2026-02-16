import logging
from .config import settings

class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Never log user raw text or extracted file contents.
        msg = record.getMessage()
        blocked_markers = ["RAW_USER_TEXT=", "FILE_TEXT="]
        for m in blocked_markers:
            if m in msg:
                record.msg = "REDACTED_LOG_BLOCKED"
                record.args = ()
        return True

def setup_logging():
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
    root = logging.getLogger()
    root.addFilter(RedactingFilter())
