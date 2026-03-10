import logging
import sys
import json
from datetime import datetime
from app.config import settings

# Structured (JSON) logging for production
USE_JSON_LOGS = getattr(settings, "APP_ENV", "development") == "production"


class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log)


def _configure_logging():
    level = logging.DEBUG if settings.APP_DEBUG else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    if USE_JSON_LOGS:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)
    return logging.getLogger("fullego")


logger = _configure_logging()

