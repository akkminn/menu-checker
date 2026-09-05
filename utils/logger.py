import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Absolute so the log lands next to the project regardless of the working
# directory the process was started from.
_DEFAULT_LOG_FILE = Path(__file__).parent.parent / "bot.log"
LOG_FILE = Path(os.getenv("LOG_FILE", _DEFAULT_LOG_FILE))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Rotate so a long-running bot cannot fill the disk: 5 MB per file, 5 kept.
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5

_stream_handler = logging.StreamHandler(sys.stdout)
if hasattr(_stream_handler.stream, "reconfigure"):
    _stream_handler.stream.reconfigure(encoding="utf-8", errors="replace")

_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=_MAX_BYTES,
    backupCount=_BACKUP_COUNT,
    encoding="utf-8",
)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[_stream_handler, _file_handler],
)
log = logging.getLogger("menu-bot")
