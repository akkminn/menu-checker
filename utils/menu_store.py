"""Persists the latest extracted menu per restaurant to disk."""
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import date as _date
from pathlib import Path

from utils.logger import log

_FILE = Path(__file__).parent.parent / "menu_store.json"
# Reentrant: save_menu calls _load() while already holding the lock.
_lock = threading.RLock()


def slug(name: str) -> str:
    """Create a short ASCII key from a restaurant name.

    Names written entirely in Burmese leave nothing behind once non-ASCII is
    stripped, so fall back to a stable digest of the original name instead of
    returning "" and colliding with every other such restaurant.
    """
    ascii_name = name.encode("ascii", "ignore").decode()
    key = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")[:40]
    if key:
        return key
    # sha1 (not hash()) so the key is stable across processes and restarts.
    digest = hashlib.sha1(name.strip().encode("utf-8")).hexdigest()[:12]
    return f"r_{digest}"


def save_menu(restaurant_name: str, items: list[str]) -> None:
    with _lock:
        store = _load()
        store[slug(restaurant_name)] = {
            "name": restaurant_name,
            "items": items,
            "date": _date.today().isoformat(),   # "2026-06-10"
        }
        _write(store)


def load_menu(restaurant_slug: str) -> tuple[str, list[str]]:
    """Return (restaurant_name, items) or ('', []) if not found."""
    with _lock:
        entry = _load().get(restaurant_slug, {})
    return entry.get("name", ""), entry.get("items", [])


def is_today(restaurant_slug: str) -> bool:
    """Return True only if the stored menu was saved today."""
    with _lock:
        entry = _load().get(restaurant_slug, {})
    return entry.get("date") == _date.today().isoformat()


def _load() -> dict:
    with _lock:
        if not _FILE.exists():
            return {}
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Writes are atomic, so this means the file was damaged out of
            # band. Degrade to an empty store rather than 500-ing the webhook.
            log.error("menu_store.json is unreadable (%s) — treating as empty", exc)
            return {}


def _write(store: dict) -> None:
    """Atomically replace the store file so readers never see a partial write."""
    with _lock:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(_FILE.parent), prefix=_FILE.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, _FILE)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
