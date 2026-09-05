"""line_reader: handler safety, dedupe and async dispatch. (findings 1, 3, 4, 7, 8)"""
import pytest
from conftest import BULLET, make_event, make_postback, menu_text

from fetcher import line_reader as lr

RESTAURANT = {
    "name": "Heaven Food & snack",
    "line_group_id": "Gout",
    "skip_images": False,
}


@pytest.fixture
def wired(monkeypatch, store, sessions):
    """line_reader with every outbound Line/AI call replaced by a recorder."""
    calls = {"sent": [], "replies": [], "dms": [], "submitted": []}

    monkeypatch.setattr(lr, "send_to_line", lambda gid, text: calls["sent"].append((gid, text)))
    monkeypatch.setattr(lr, "send_reply", lambda tok, text: calls["replies"].append(text))
    monkeypatch.setattr(lr, "send_order_start_dm", lambda *a, **k: calls["dms"].append(a))
    monkeypatch.setattr(lr, "send_qty_selection_dm", lambda *a, **k: None)
    monkeypatch.setattr(lr, "send_order_update_dm", lambda *a, **k: None)
    monkeypatch.setattr(lr, "send_order_summary_dm", lambda *a, **k: None)
    monkeypatch.setattr(lr, "get_line_image_bytes", lambda mid: b"image-bytes")
    monkeypatch.setattr(lr, "_get_restaurant", lambda gid: dict(RESTAURANT))
    # restaurants.json is local config and absent from a fresh clone.
    monkeypatch.setattr(lr, "load_restaurants", lambda: [dict(RESTAURANT, line_contact="")])
    monkeypatch.setattr(lr, "extract_all_menus",
                        lambda posts: menu_text("Heaven Food & snack", ["fried rice", "tea"]))
    monkeypatch.setattr(lr, "extract_menu_from_image_bytes",
                        lambda b, n: menu_text("Heaven Food & snack", ["fried rice", "tea"]))
    # Run "background" work inline so tests stay deterministic.
    monkeypatch.setattr(lr, "_submit",
                        lambda fn, *a: (calls["submitted"].append(fn.__name__), fn(*a)))
    lr._seen_events.clear()
    return calls


# ── Finding 1: image menus must be persisted, not just forwarded ──

def test_image_menu_is_persisted_so_order_button_works(wired, store):
    lr.handle_image(make_event(
        {"group_id": "Gsrc"}, message=type("M", (), {"id": "m1"})()
    ))

    assert len(wired["sent"]) == 1
    name, items = store.load_menu("heaven_food_snack")
    assert items == [BULLET + "fried rice", BULLET + "tea"]
    assert store.is_today("heaven_food_snack") is True


def test_text_menu_is_persisted(wired, store):
    lr.handle_text(make_event({"group_id": "Gsrc"}, message=type("M", (), {"text": "menu!"})()))
    assert store.is_today("heaven_food_snack") is True


def test_image_skipped_when_configured(wired, monkeypatch, store):
    monkeypatch.setattr(lr, "_get_restaurant", lambda gid: {**RESTAURANT, "skip_images": True})
    lr.handle_image(make_event({"group_id": "Gsrc"}, message=type("M", (), {"id": "m1"})()))
    assert wired["sent"] == []


# ── Finding 8: fast webhook + no duplicate work on redelivery ──

def test_work_is_handed_to_a_worker(wired):
    lr.handle_text(make_event({"group_id": "Gsrc"}, message=type("M", (), {"text": "hi"})()))
    assert wired["submitted"] == ["_process_text"]


def test_redelivered_event_is_ignored(wired):
    event = make_event(
        {"group_id": "Gsrc"},
        message=type("M", (), {"text": "menu"})(),
        webhook_event_id="evt-1",
    )
    lr.handle_text(event)
    lr.handle_text(event)  # Line redelivers with the same webhookEventId
    assert len(wired["sent"]) == 1


def test_distinct_events_both_processed(wired):
    for eid in ("evt-1", "evt-2"):
        lr.handle_text(make_event(
            {"group_id": "Gsrc"},
            message=type("M", (), {"text": "menu"})(),
            webhook_event_id=eid,
        ))
    assert len(wired["sent"]) == 2


def test_seen_event_cache_is_bounded(wired):
    for i in range(lr._SEEN_EVENTS_MAX + 50):
        lr._is_duplicate(make_event({"group_id": "G"}, webhook_event_id="e%d" % i))
    assert len(lr._seen_events) <= lr._SEEN_EVENTS_MAX


def test_worker_failure_does_not_escape(monkeypatch, wired):
    """A failing extraction must not take down the request thread."""
    monkeypatch.setattr(lr, "extract_all_menus", lambda posts: 1 / 0)
    lr.handle_text(make_event({"group_id": "Gsrc"}, message=type("M", (), {"text": "hi"})()))
    assert wired["sent"] == []


# ── Finding 3: hostile / stale postbacks must never reach Flask as a 500 ──

@pytest.mark.parametrize("data", [
    "action=select_qty&r=heaven_food_snack&i=99",   # index past end of menu
    "action=select_qty&r=heaven_food_snack&i=-1",   # negative index
    "action=select_qty&r=heaven_food_snack&i=abc",  # non-numeric
    "action=select_qty&r=some_other_place&i=0",     # wrong restaurant
    "action=add_item&r=heaven_food_snack&i=0&q=999",
    "action=add_item&r=heaven_food_snack&i=0&q=0",
    "action=unknown_action",
    "garbage-without-equals",
    "",
])
def test_malformed_postback_never_raises(wired, sessions, data):
    sessions.start("U9", "heaven_food_snack", "Heaven Food & snack", ["• a", "• b"])
    lr.handle_postback(make_postback(data))  # must not raise


def test_postback_without_user_id_ignored(wired):
    event = make_event({}, postback=type("P", (), {"data": "action=order&r=x"})(), reply_token="t")
    lr.handle_postback(event)
    assert wired["replies"] == []


def test_handler_swallows_downstream_line_errors(monkeypatch, wired, sessions):
    def boom(*a, **k):
        raise RuntimeError("Line API down")

    monkeypatch.setattr(lr, "send_reply", boom)
    sessions.start("U9", "heaven_food_snack", "Heaven", ["• a"])
    lr.handle_postback(make_postback("action=select_qty&r=heaven_food_snack&i=99"))


def test_duplicate_postback_does_not_double_add(wired, sessions):
    sessions.start("U9", "heaven_food_snack", "Heaven", ["• a", "• b"])
    lr.handle_postback(make_postback("action=select_qty&r=heaven_food_snack&i=0", event_id="p1"))
    lr.handle_postback(make_postback("action=add_item&r=heaven_food_snack&i=0&q=2", event_id="p2"))
    lr.handle_postback(make_postback("action=add_item&r=heaven_food_snack&i=0&q=2", event_id="p2"))
    assert sessions.get("U9")["selected"][0]["qty"] == 2


# ── Finding 4: a failed opening DM must not lock the user out ──

def test_failed_dm_clears_the_session(monkeypatch, wired, store, sessions):
    store.save_menu("Heaven Food & snack", ["• a", "• b"])

    def refuse(*a, **k):
        raise RuntimeError("403 not a friend")

    monkeypatch.setattr(lr, "send_order_start_dm", refuse)
    lr.handle_postback(make_postback("action=order&r=heaven_food_snack"))

    assert sessions.get("U9") is None
    assert "friend" in wired["replies"][-1]


def test_user_can_order_again_after_dm_failure(monkeypatch, wired, store, sessions):
    store.save_menu("Heaven Food & snack", ["• a"])
    monkeypatch.setattr(lr, "send_order_start_dm",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    lr.handle_postback(make_postback("action=order&r=heaven_food_snack"))

    monkeypatch.setattr(lr, "send_order_start_dm", lambda *a, **k: None)
    lr.handle_postback(make_postback("action=order&r=heaven_food_snack", event_id="p2"))
    assert sessions.get("U9") is not None


def test_order_blocked_when_menu_is_not_todays(wired, store, sessions):
    lr.handle_postback(make_postback("action=order&r=heaven_food_snack"))
    assert sessions.get("U9") is None
    assert wired["replies"], "user should be told the menu is not ready"


def test_full_order_flow(wired, store, sessions):
    store.save_menu("Heaven Food & snack", ["• rice", "• tea"])
    lr.handle_postback(make_postback("action=order&r=heaven_food_snack", event_id="a"))
    lr.handle_postback(make_postback("action=select_qty&r=heaven_food_snack&i=0", event_id="b"))
    lr.handle_postback(make_postback("action=add_item&r=heaven_food_snack&i=0&q=3", event_id="c"))
    assert sessions.get("U9")["selected"] == [{"idx": 0, "item": "• rice", "qty": 3}]

    lr.handle_postback(make_postback("action=done_order", event_id="d"))
    assert sessions.get("U9") is None, "done_order must release the session"


# ── Finding 7/15: the app exposes a health probe and rejects bad signatures ──

def test_health_endpoint():
    client = lr.app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_webhook_rejects_invalid_signature():
    client = lr.app.test_client()
    response = client.post("/webhook", data="{}", headers={"X-Line-Signature": "nope"})
    assert response.status_code == 400
