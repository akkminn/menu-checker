"""order_session: bounds, restaurant matching, expiry. (review findings 3, 5, 9)"""

ITEMS = ["• one", "• two", "• three"]


def test_in_range_index_accepted(sessions):
    sessions.start("U1", "fortune", "Fortune", ITEMS)
    assert sessions.set_pending_item("U1", 2, "fortune") is not None


def test_out_of_range_index_rejected(sessions):
    """Finding 3: an unchecked index used to raise IndexError -> HTTP 500."""
    sessions.start("U1", "fortune", "Fortune", ITEMS)
    assert sessions.set_pending_item("U1", 99, "fortune") is None
    assert sessions.set_pending_item("U1", -1, "fortune") is None


def test_index_from_another_restaurant_rejected(sessions):
    """Finding 9: indices must not cross between restaurants."""
    sessions.start("U1", "fortune", "Fortune", ITEMS)
    assert sessions.set_pending_item("U1", 1, "tamar_myay") is None
    assert sessions.confirm_item("U1", 1, "tamar_myay") is None


def test_no_session_returns_none(sessions):
    assert sessions.set_pending_item("nobody", 0, "fortune") is None
    assert sessions.confirm_item("nobody", 1, "fortune") is None
    assert sessions.get("nobody") is None


def test_confirm_records_selected_item(sessions):
    sessions.start("U1", "fortune", "Fortune", ITEMS)
    sessions.set_pending_item("U1", 1, "fortune")
    session = sessions.confirm_item("U1", 2, "fortune")
    assert session["selected"] == [{"idx": 1, "item": "• two", "qty": 2}]


def test_repeat_selection_accumulates_quantity(sessions):
    sessions.start("U1", "fortune", "Fortune", ITEMS)
    sessions.set_pending_item("U1", 1, "fortune")
    sessions.confirm_item("U1", 2, "fortune")
    sessions.set_pending_item("U1", 1, "fortune")
    session = sessions.confirm_item("U1", 3, "fortune")
    assert len(session["selected"]) == 1
    assert session["selected"][0]["qty"] == 5


def test_confirm_without_pending_item_rejected(sessions):
    sessions.start("U1", "fortune", "Fortune", ITEMS)
    assert sessions.confirm_item("U1", 1, "fortune") is None


def test_abandoned_session_expires(sessions):
    """Finding 5: an unfinished order used to block the user forever."""
    sessions.start("U2", "fortune", "Fortune", ITEMS)
    sessions._sessions["U2"]["started_at"] -= sessions.SESSION_TTL_SECONDS + 1
    assert sessions.get("U2") is None
    assert "U2" not in sessions._sessions


def test_fresh_session_survives_purge(sessions):
    sessions.start("U2", "fortune", "Fortune", ITEMS)
    sessions.start("U3", "fortune", "Fortune", ITEMS)
    sessions._sessions["U2"]["started_at"] -= sessions.SESSION_TTL_SECONDS + 1
    assert sessions.get("U3") is not None
    assert sessions.get("U2") is None


def test_end_returns_and_clears(sessions):
    sessions.start("U1", "fortune", "Fortune", ITEMS)
    assert sessions.end("U1") is not None
    assert sessions.get("U1") is None
    assert sessions.end("U1") is None


def test_start_copies_items(sessions):
    """A later mutation of the caller's list must not rewrite the session."""
    items = list(ITEMS)
    sessions.start("U1", "fortune", "Fortune", items)
    items.append("• four")
    assert len(sessions.get("U1")["all_items"]) == 3
