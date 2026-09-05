from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
    FlexMessage,
    FlexBubble,
    FlexCarousel,
    FlexBox,
    FlexText,
    FlexSeparator,
    FlexButton,
    QuickReply,
    QuickReplyItem,
    PostbackAction,
    URIAction,
)

from config import LINE_CHANNEL_ACCESS_TOKEN
from extractor.prompt import today_short
from utils.logger import log
from utils.menu_store import slug as make_slug

# If the difference between the restaurant with the most items and the one
# with the fewest is within this threshold, we use a horizontally-scrollable
# FlexCarousel (all cards same height looks fine).  Beyond it we fall back to
# separate FlexMessages so tall cards don't force blank space on short ones.
_CAROUSEL_DIFF_THRESHOLD = 5

# Line's hard limits: a carousel holds at most 12 bubbles, and a single push
# carries at most 5 messages. Exceeding either is a 400 from the API.
_MAX_CAROUSEL_BUBBLES = 12
_MAX_MESSAGES_PER_PUSH = 5

# ─────────────────────────────────────────────
#  Colours
# ─────────────────────────────────────────────
HEADER_BG    = "#D35400"
SUBTITLE_CLR = "#E67E22"
ITEM_CLR     = "#2C3E50"
DATE_CLR     = "#FAD7A0"
BTN_CLR      = "#922B21"


# ─────────────────────────────────────────────
#  Menu text parser  (used by pipeline too)
# ─────────────────────────────────────────────
def parse_menu_message(text: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """Parse formatted menu text → (date_header, [(restaurant_name, [items])])."""
    date_header = ""
    restaurants: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_items: list[str] = []
    in_items = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("🗓"):
            date_header = line
        elif line.startswith("🍽"):
            if current_name is not None:
                restaurants.append((current_name, current_items))
            current_name = line.lstrip("🍽").strip()
            current_items = []
            in_items = False
        elif line.startswith("📋"):
            in_items = True
        elif all(c in "━─— " for c in line):
            pass
        elif in_items and line:
            item = line if line.startswith("•") else f"• {line}"
            current_items.append(item)

    if current_name is not None:
        restaurants.append((current_name, current_items))

    return date_header, restaurants


# ─────────────────────────────────────────────
#  Flex bubble builder
# ─────────────────────────────────────────────
def _build_bubble(name: str, items: list[str]) -> FlexBubble:
    restaurant_slug = make_slug(name)

    # Header — date always shown on every card
    header_contents: list = [
        FlexText(text=today_short(), size="xs", color=DATE_CLR, weight="bold"),
        FlexText(text=f"🍽  {name}", weight="bold", color="#FFFFFF", size="lg", wrap=True),
    ]

    # Body
    body_contents: list = [
        FlexText(
            text="📋  ရရှိနိုင်သော menu များ",
            weight="bold",
            color=SUBTITLE_CLR,
            size="sm",
        ),
        FlexSeparator(margin="sm"),
    ]
    for item in items:
        body_contents.append(
            FlexBox(
                layout="vertical",
                margin="sm",
                padding_bottom="xs",
                contents=[FlexText(text=item, size="sm", color=ITEM_CLR, wrap=True)],
            )
        )

    # Footer — Order button
    footer = FlexBox(
        layout="vertical",
        padding_all="md",
        contents=[
            FlexButton(
                action=PostbackAction(
                    label="🛒  မှာယူမည်",
                    data=f"action=order&r={restaurant_slug}",
                ),
                style="primary",
                color=BTN_CLR,
                height="sm",
            )
        ],
    )

    return FlexBubble(
        header=FlexBox(
            layout="vertical",
            background_color=HEADER_BG,
            padding_all="md",
            contents=header_contents,
        ),
        body=FlexBox(
            layout="vertical",
            spacing="none",
            padding_all="md",
            padding_bottom="lg",
            contents=body_contents,
        ),
        footer=footer,
    )


def _build_flex_messages(menu_text: str) -> list[FlexMessage]:
    """
    Build Flex Messages for all restaurants.

    Strategy:
    • If the spread between the longest and shortest menu is within
      _CAROUSEL_DIFF_THRESHOLD items → single horizontally-scrollable
      FlexCarousel (better UX, cards look even).
    • Otherwise → one separate FlexMessage per restaurant so tall cards
      don't force blank space on short ones.
    """
    _, restaurants = parse_menu_message(menu_text)
    if not restaurants:
        return []

    bubbles = [_build_bubble(name, items) for name, items in restaurants]

    if len(restaurants) == 1:
        # Single restaurant — no carousel needed
        name, _ = restaurants[0]
        return [FlexMessage(alt_text=f"🍽 {name}", contents=bubbles[0])]

    counts = [len(items) for _, items in restaurants]
    spread = max(counts) - min(counts)

    if spread <= _CAROUSEL_DIFF_THRESHOLD:
        log.info(
            "Item spread %d ≤ %d → using FlexCarousel",
            spread, _CAROUSEL_DIFF_THRESHOLD,
        )
        # Split across several carousels once past Line's 12-bubble ceiling.
        return [
            FlexMessage(
                alt_text="🍽 Today's Menus",
                contents=FlexCarousel(contents=bubbles[i:i + _MAX_CAROUSEL_BUBBLES]),
            )
            for i in range(0, len(bubbles), _MAX_CAROUSEL_BUBBLES)
        ]
    else:
        log.info(
            "Item spread %d > %d → using separate FlexMessages",
            spread, _CAROUSEL_DIFF_THRESHOLD,
        )
        return [
            FlexMessage(alt_text=f"🍽 {name}", contents=bubble)
            for (name, _), bubble in zip(restaurants, bubbles)
        ]


# ─────────────────────────────────────────────
#  Order DM helpers
# ─────────────────────────────────────────────
_MAX_QUICK_REPLY = 12   # Line allows max 13; reserve 1 for Done


def _item_quick_reply(
    restaurant_slug: str,
    all_items: list[str],
    already_selected_idxs: set[int],
) -> QuickReply:
    remaining = [
        (i, item) for i, item in enumerate(all_items)
        if i not in already_selected_idxs
    ]
    items_payload = [
        QuickReplyItem(
            action=PostbackAction(
                label=item.replace("• ", "")[:20],
                data=f"action=select_qty&r={restaurant_slug}&i={idx}",
            )
        )
        for idx, item in remaining[:_MAX_QUICK_REPLY]
    ]
    items_payload.append(
        QuickReplyItem(
            action=PostbackAction(label="✅  ပြီးပြီ", data="action=done_order")
        )
    )
    return QuickReply(items=items_payload)


def send_order_start_dm(user_id: str, restaurant_slug: str, restaurant_name: str, all_items: list[str]) -> None:
    items_text = "\n".join(all_items)
    text = (
        f"🍽  {restaurant_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"မှာလိုသော menu ကို ရွေးချယ်ပါ 👇\n\n"
        f"{items_text}"
    )
    _push(user_id, TextMessage(
        text=text,
        quick_reply=_item_quick_reply(restaurant_slug, all_items, set()),
    ))


def send_qty_selection_dm(
    user_id: str,
    restaurant_slug: str,
    item_idx: int,
    item_text: str,
) -> None:
    """Ask how many of the selected item the user wants."""
    label = item_text.replace("• ", "")
    text = f"🍴  {label}\nဘယ်နှစ်ပွဲ မှာလိုသလဲ?"
    qty_items = [
        QuickReplyItem(
            action=PostbackAction(
                label=str(q),
                data=f"action=add_item&r={restaurant_slug}&i={item_idx}&q={q}",
            )
        )
        for q in range(1, 11)       # 1 – 10 portions
    ]
    _push(user_id, TextMessage(text=text, quick_reply=QuickReply(items=qty_items)))


def send_order_update_dm(
    user_id: str,
    restaurant_slug: str,
    selected: list[dict],
    all_items: list[str],
) -> None:
    """Show current order so far and offer remaining items."""
    lines = [f"  • {e['item'].replace('• ', '')} x{e['qty']}" for e in selected]
    selected_text = "\n".join(lines)
    already_idxs = {e["idx"] for e in selected}
    remaining = [(i, item) for i, item in enumerate(all_items) if i not in already_idxs]

    if remaining:
        text = (
            f"📝  လက်ရှိ မှာထားသည်:\n{selected_text}\n\n"
            f"နောက်ထပ် မှာလိုပါသလား?"
        )
        quick_items = [
            QuickReplyItem(
                action=PostbackAction(
                    label=item.replace("• ", "")[:20],
                    data=f"action=select_qty&r={restaurant_slug}&i={idx}",
                )
            )
            for idx, item in remaining[:_MAX_QUICK_REPLY]
        ]
        quick_items.append(QuickReplyItem(
            action=PostbackAction(label="✅  ပြီးပြီ", data="action=done_order")
        ))
        _push(user_id, TextMessage(text=text, quick_reply=QuickReply(items=quick_items)))
    else:
        _push(user_id, TextMessage(
            text=f"📝  လက်ရှိ မှာထားသည်:\n{selected_text}\n\n(menu အားလုံး ရွေးချယ်ပြီးပါပြီ)\n"
                 f"✅ ပြီးပြီ ကို နှိပ်ပါ",
            quick_reply=QuickReply(items=[QuickReplyItem(
                action=PostbackAction(label="✅  ပြီးပြီ", data="action=done_order")
            )])
        ))


def send_order_summary_dm(
    user_id: str,
    restaurant_name: str,
    selected: list[dict],
    line_contact: str = "",
) -> None:
    """Send final order summary. Adds a contact button if line_contact is provided."""
    lines = [f"• {e['item'].replace('• ', '')} x{e['qty']}" for e in selected]
    items_text = "\n".join(lines)
    summary_text = (
        f"✅  သင်၏ မှာယူမှု\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🍽  {restaurant_name}\n\n"
        f"{items_text}"
    )

    if line_contact:
        # Flex bubble: summary text + contact button
        bubble = FlexBubble(
            body=FlexBox(
                layout="vertical",
                padding_all="lg",
                padding_bottom="xl",
                contents=[
                    FlexText(
                        text=summary_text,
                        wrap=True,
                        size="sm",
                        color=ITEM_CLR,
                    )
                ],
            ),
            footer=FlexBox(
                layout="vertical",
                padding_all="md",
                contents=[
                    FlexButton(
                        action=URIAction(
                            label="📲  Restaurant ဆီ ဆက်သွယ်မည်",
                            uri=line_contact,
                        ),
                        style="primary",
                        color=BTN_CLR,
                        height="sm",
                    )
                ],
            ),
        )
        _push(user_id, FlexMessage(alt_text="Order Summary", contents=bubble))
    else:
        # Plain TextMessage — user can long-press → Copy to grab the full order
        _push(user_id, TextMessage(text=summary_text))


def send_reply(reply_token: str, text: str) -> None:
    """Reply in the group/chat using a reply token (no friend required)."""
    with ApiClient(_config()) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )


# ─────────────────────────────────────────────
#  Public send API
# ─────────────────────────────────────────────
def _config() -> Configuration:
    return Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)


def _push(to: str, message) -> None:
    with ApiClient(_config()) as api_client:
        MessagingApi(api_client).push_message(
            PushMessageRequest(to=to, messages=[message])
        )


def send_to_line(group_id: str, menu_text: str) -> None:
    messages = _build_flex_messages(menu_text)

    if not messages:
        log.warning("Flex parsing failed — falling back to plain text for %s", group_id)
        _push(group_id, TextMessage(text=menu_text))
        return

    log.info("Sending %d Flex Message(s) to %s", len(messages), group_id)

    # Line allows max 5 messages per push — chunk if needed
    for i in range(0, len(messages), _MAX_MESSAGES_PER_PUSH):
        chunk = messages[i:i + _MAX_MESSAGES_PER_PUSH]
        with ApiClient(_config()) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(to=group_id, messages=chunk)
            )


def get_line_image_bytes(message_id: str) -> bytes:
    with ApiClient(_config()) as api_client:
        return MessagingApiBlob(api_client).get_message_content(message_id)


def get_group_id_webhook_app():
    from flask import Flask, request as flask_request
    from linebot.v3 import WebhookHandler
    from linebot.v3.webhooks import JoinEvent
    import os

    app = Flask(__name__)
    handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

    @app.route("/webhook", methods=["POST"])
    def webhook():
        signature = flask_request.headers["X-Line-Signature"]
        body = flask_request.get_data(as_text=True)
        handler.handle(body, signature)
        return "OK"

    @handler.add(JoinEvent)
    def handle_join(event):
        print(f"Bot joined group: {event.source.group_id}")

    return app
