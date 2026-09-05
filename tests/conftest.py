"""Shared test setup.

Dummy credentials are installed before anything imports config, so the suite
never depends on (or touches) the developer's real .env. load_dotenv() does not
override variables that are already set, so these win.
"""
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")

import pytest  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """menu_store backed by a throwaway file instead of the real one."""
    from utils import menu_store

    monkeypatch.setattr(menu_store, "_FILE", tmp_path / "menu_store.json")
    return menu_store


@pytest.fixture
def sessions():
    """order_session with a clean slate before and after each test."""
    from utils import order_session

    order_session._sessions.clear()
    yield order_session
    order_session._sessions.clear()


def make_event(source: dict, **fields):
    """Build a stand-in for a Line webhook event object."""
    fields.setdefault("webhook_event_id", None)
    return types.SimpleNamespace(source=types.SimpleNamespace(**source), **fields)


def make_postback(data: str, user_id: str = "U9", event_id: str | None = None):
    return make_event(
        {"user_id": user_id},
        postback=types.SimpleNamespace(data=data),
        reply_token="tok",
        webhook_event_id=event_id,
    )


BULLET = "\N{BULLET} "


def menu_text(name: str, items: list[str]) -> str:
    """Build a menu message in the format the AI is prompted to produce."""
    nl = chr(10)
    body = nl.join(BULLET + i for i in items)
    return (
        "\N{FORK AND KNIFE WITH PLATE} " + name + nl
        + "\N{BOX DRAWINGS HEAVY HORIZONTAL}" * 8 + nl
        + "\N{CLIPBOARD} menu" + nl + nl
        + body
    )
