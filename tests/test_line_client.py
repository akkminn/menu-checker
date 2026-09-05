"""line_client: menu parsing and Line's message/carousel limits. (review finding 11)"""
from conftest import BULLET, menu_text

from sender import line_client as lc


def test_parse_menu_message_extracts_restaurants_and_items():
    text = menu_text("Fortune", ["fried rice", "tea"])
    _, restaurants = lc.parse_menu_message(text)
    assert restaurants == [("Fortune", [BULLET + "fried rice", BULLET + "tea"])]


def test_parse_menu_message_handles_multiple_restaurants():
    text = menu_text("Fortune", ["rice"]) + chr(10) + menu_text("Heaven", ["tea", "soup"])
    _, restaurants = lc.parse_menu_message(text)
    assert [name for name, _ in restaurants] == ["Fortune", "Heaven"]
    assert len(restaurants[1][1]) == 2


def test_parse_menu_message_adds_missing_bullets():
    nl = chr(10)
    text = "🍽 Fortune" + nl + "📋 menu" + nl + "plain item"
    _, restaurants = lc.parse_menu_message(text)
    assert restaurants[0][1] == [BULLET + "plain item"]


def test_single_restaurant_is_one_message():
    messages = lc._build_flex_messages(menu_text("Fortune", ["rice"]))
    assert len(messages) == 1


def test_carousel_respects_line_12_bubble_limit():
    """Finding 11: a 13-bubble carousel is a 400 from the Line API."""
    nl = chr(10)
    # Equal item counts keep the spread at 0, which selects the carousel branch.
    text = nl.join(menu_text("Rest %d" % i, ["dish"]) for i in range(13))
    messages = lc._build_flex_messages(text)

    bubble_counts = [len(m.contents.contents) for m in messages]
    assert sum(bubble_counts) == 13
    assert all(c <= lc._MAX_CAROUSEL_BUBBLES for c in bubble_counts)


def test_uneven_menus_fall_back_to_separate_messages():
    nl = chr(10)
    text = (menu_text("Small", ["a"]) + nl
            + menu_text("Big", ["d%d" % i for i in range(20)]))
    messages = lc._build_flex_messages(text)
    assert len(messages) == 2


def test_unparseable_text_falls_back_to_plain_push(monkeypatch):
    pushed = []
    monkeypatch.setattr(lc, "_push", lambda to, msg: pushed.append((to, msg)))
    lc.send_to_line("Ggroup", "just some text with no menu markers")
    assert len(pushed) == 1


def test_push_is_chunked_to_five_messages(monkeypatch):
    """Line rejects a push carrying more than 5 messages."""
    nl = chr(10)
    # Wildly uneven item counts force the separate-message branch.
    text = nl.join(menu_text("R%d" % i, ["d%d" % j for j in range(i * 4 + 1)])
                   for i in range(7))
    chunks = []

    class FakeApi:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(lc, "ApiClient", FakeApi)
    monkeypatch.setattr(
        lc, "MessagingApi",
        lambda client: type("M", (), {
            "push_message": staticmethod(lambda req: chunks.append(len(req.messages)))
        })(),
    )

    lc.send_to_line("Ggroup", text)
    assert chunks, "expected at least one push"
    assert all(n <= lc._MAX_MESSAGES_PER_PUSH for n in chunks)
    assert sum(chunks) == 7


def test_quick_reply_stays_within_line_limit():
    items = ["• item %d" % i for i in range(30)]
    qr = lc._item_quick_reply("fortune", items, set())
    # 12 item buttons + the Done button; Line allows 13.
    assert len(qr.items) == lc._MAX_QUICK_REPLY + 1
    assert all(len(i.action.label) <= 20 for i in qr.items)
