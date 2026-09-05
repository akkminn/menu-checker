"""In-memory order sessions — tracks each user's item + quantity selection."""
import threading
import time

_sessions: dict[str, dict] = {}
_lock = threading.Lock()

# Abandoned sessions are dropped after this long so a user who never taps
# "✅ ပြီးပြီ" is not locked out of ordering forever.
SESSION_TTL_SECONDS = 2 * 60 * 60


def _purge_expired_locked() -> None:
    """Drop timed-out sessions. Caller must hold _lock."""
    cutoff = time.monotonic() - SESSION_TTL_SECONDS
    for user_id in [u for u, s in _sessions.items() if s["started_at"] < cutoff]:
        del _sessions[user_id]


def _valid_locked(user_id: str, restaurant_slug: str | None) -> dict | None:
    """Return the live session if it exists and matches restaurant_slug."""
    session = _sessions.get(user_id)
    if not session:
        return None
    if restaurant_slug and session["slug"] != restaurant_slug:
        return None
    return session


def start(user_id: str, restaurant_slug: str, restaurant_name: str, all_items: list[str]) -> None:
    with _lock:
        _purge_expired_locked()
        _sessions[user_id] = {
            "slug": restaurant_slug,
            "name": restaurant_name,
            "all_items": list(all_items),
            "selected": [],          # [{"idx": 0, "item": "• ...", "qty": 2}]
            "pending_idx": None,     # item index waiting for qty confirmation
            "started_at": time.monotonic(),
        }


def set_pending_item(user_id: str, item_idx: int, restaurant_slug: str = "") -> dict | None:
    """Mark an item as selected, waiting for qty input.

    Returns None if there is no live session, the postback belongs to a
    different restaurant, or item_idx is out of range for this session.
    """
    with _lock:
        _purge_expired_locked()
        session = _valid_locked(user_id, restaurant_slug)
        if not session:
            return None
        if not 0 <= item_idx < len(session["all_items"]):
            return None
        session["pending_idx"] = item_idx
        return dict(session)


def confirm_item(user_id: str, qty: int, restaurant_slug: str = "") -> dict | None:
    """Confirm the pending item with a quantity."""
    with _lock:
        _purge_expired_locked()
        session = _valid_locked(user_id, restaurant_slug)
        if not session or session["pending_idx"] is None:
            return None
        idx = session["pending_idx"]
        if not 0 <= idx < len(session["all_items"]):
            session["pending_idx"] = None
            return None
        item = session["all_items"][idx]
        session["pending_idx"] = None
        # Update qty if already in list, else append
        for entry in session["selected"]:
            if entry["idx"] == idx:
                entry["qty"] += qty
                return dict(session)
        session["selected"].append({"idx": idx, "item": item, "qty": qty})
        return dict(session)


def get(user_id: str) -> dict | None:
    with _lock:
        _purge_expired_locked()
        session = _sessions.get(user_id)
        return dict(session) if session else None


def end(user_id: str) -> dict | None:
    with _lock:
        _purge_expired_locked()
        return _sessions.pop(user_id, None)
