import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    """Read a required setting, failing with an actionable message."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from None


GOOGLE_API_KEY: str = _require("GOOGLE_API_KEY")
LINE_CHANNEL_ACCESS_TOKEN: str = _require("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET: str = _require("LINE_CHANNEL_SECRET")

SCHEDULE_HOUR: int = _int_env("SCHEDULE_HOUR", 8)
SCHEDULE_MINUTE: int = _int_env("SCHEDULE_MINUTE", 0)
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Bangkok")

# Web server
PORT: int = _int_env("PORT", 5000)
HOST: str = os.getenv("HOST", "0.0.0.0")
# Threads serving webhook requests in the production (waitress) server.
SERVER_THREADS: int = _int_env("SERVER_THREADS", 8)
# Background workers that run the slow AI extraction off the request thread.
WEBHOOK_WORKERS: int = _int_env("WEBHOOK_WORKERS", 4)

# Local config, not in version control — it holds your Line group IDs.
_RESTAURANTS_FILE = Path(
    os.getenv("RESTAURANTS_FILE", Path(__file__).parent / "restaurants.json")
)
_RESTAURANTS_EXAMPLE = Path(__file__).parent / "restaurants.example.json"


def load_restaurants() -> list[dict]:
    if not _RESTAURANTS_FILE.exists():
        raise RuntimeError(
            f"{_RESTAURANTS_FILE.name} not found. "
            f"Copy {_RESTAURANTS_EXAMPLE.name} to {_RESTAURANTS_FILE.name} "
            f"and fill in your restaurants."
        )
    with open(_RESTAURANTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def build_source_group_map() -> dict[str, dict]:
    """Return {source_line_group_id: restaurant_dict} for Line webhook routing."""
    result = {}
    for r in load_restaurants():
        src = r.get("source_line_group_id")
        if src:
            result[src] = r
    return result
