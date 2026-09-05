import atexit
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
    JoinEvent,
    PostbackEvent,
)

from config import (
    LINE_CHANNEL_SECRET,
    WEBHOOK_WORKERS,
    build_source_group_map,
    load_restaurants,
)
from extractor.gemini_client import extract_all_menus, extract_menu_from_image_bytes
from sender.line_client import (
    send_to_line,
    send_reply,
    send_order_start_dm,
    send_qty_selection_dm,
    send_order_update_dm,
    send_order_summary_dm,
    get_line_image_bytes,
    parse_menu_message,
)
from utils.logger import log
from utils.menu_store import save_menu, load_menu, is_today, slug as make_slug
from utils import order_session

app = Flask(__name__)
_handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ─────────────────────────────────────────────
#  Background workers
#
#  Line expects a prompt 200 from the webhook. Menu extraction takes seconds
#  (longer when the AI call retries), so the request thread only validates and
#  hands off — otherwise Line times out and redelivers the same event, and the
#  group receives the menu twice.
# ─────────────────────────────────────────────
_executor = ThreadPoolExecutor(
    max_workers=WEBHOOK_WORKERS, thread_name_prefix="menu-worker"
)

# Line redelivers a failed webhook with the same webhookEventId; remember the
# recent ones so a retry never re-runs work that already succeeded.
_SEEN_EVENTS_MAX = 2000
_seen_events: OrderedDict[str, None] = OrderedDict()
_seen_lock = threading.Lock()


def _is_duplicate(event) -> bool:
    """True if this webhook event was already accepted (Line redelivery)."""
    event_id = getattr(event, "webhook_event_id", None)
    if not event_id:
        return False
    with _seen_lock:
        if event_id in _seen_events:
            return True
        _seen_events[event_id] = None
        while len(_seen_events) > _SEEN_EVENTS_MAX:
            _seen_events.popitem(last=False)
    return False


def _submit(fn, *args) -> None:
    """Run fn(*args) on a worker thread, logging anything it raises."""
    def _run():
        try:
            fn(*args)
        except Exception:
            log.exception("Background task %s failed", getattr(fn, "__name__", fn))

    _executor.submit(_run)


def shutdown_workers(wait: bool = True) -> None:
    """Let in-flight extractions finish before the process exits."""
    _executor.shutdown(wait=wait)


atexit.register(shutdown_workers, False)


def _get_restaurant(group_id: str) -> dict | None:
    return build_source_group_map().get(group_id)


# ─────────────────────────────────────────────
#  Webhook entry point
# ─────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        _handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@app.route("/health", methods=["GET"])
def health():
    """Liveness probe for the process manager / load balancer."""
    return jsonify(
        status="ok",
        pending_orders=len(order_session._sessions),
        workers=WEBHOOK_WORKERS,
    )


# ─────────────────────────────────────────────
#  Bot joined a group
# ─────────────────────────────────────────────
@_handler.add(JoinEvent)
def handle_join(event):
    if hasattr(event.source, "group_id"):
        log.info("Bot joined group: %s", event.source.group_id)


# ─────────────────────────────────────────────
#  Text message from a restaurant group
# ─────────────────────────────────────────────
def _process_text(restaurant: dict, text: str) -> None:
    """Extract and forward a menu. Runs on a worker thread."""
    try:
        menu = extract_all_menus([(restaurant["name"], [text])])
        if menu:
            # Save parsed items for ordering
            _, parsed = parse_menu_message(menu)
            for name, items in parsed:
                save_menu(name, items)

            send_to_line(restaurant["line_group_id"], menu)
            log.info("Menu forwarded from Line group for '%s'", restaurant["name"])
        else:
            log.info("Not a menu post from '%s' — skipped", restaurant["name"])
    except Exception as exc:
        log.error("Error processing text from '%s': %s", restaurant["name"], exc)


@_handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    if not hasattr(event.source, "group_id"):
        return

    group_id = event.source.group_id
    log.info("Message received from group_id: %s", group_id)

    restaurant = _get_restaurant(group_id)
    if not restaurant:
        log.info("Group %s is not in source map — add it to restaurants.json if needed", group_id)
        return

    if _is_duplicate(event):
        log.info("Duplicate delivery for group %s — ignored", group_id)
        return

    text = event.message.text
    log.info("Line text from '%s': %s", restaurant["name"], text[:80])
    _submit(_process_text, restaurant, text)


# ─────────────────────────────────────────────
#  Image message from a restaurant group
# ─────────────────────────────────────────────
def _process_image(restaurant: dict, message_id: str) -> None:
    """Download, extract and forward an image menu. Runs on a worker thread."""
    try:
        image_bytes = get_line_image_bytes(message_id)
        menu = extract_menu_from_image_bytes(image_bytes, restaurant["name"])
        if menu:
            # Persist items so the Order button can look them up, exactly as
            # the text path does — without this the card's button always fails
            # the is_today() guard.
            _, parsed = parse_menu_message(menu)
            for name, items in parsed:
                save_menu(name, items)

            send_to_line(restaurant["line_group_id"], menu)
            log.info("Image menu forwarded for '%s'", restaurant["name"])
        else:
            log.info("Image from '%s' is not a menu — skipped", restaurant["name"])
    except Exception as exc:
        log.error("Failed to process image from '%s': %s", restaurant["name"], exc)


@_handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    if not hasattr(event.source, "group_id"):
        return

    group_id = event.source.group_id
    log.info("Image received from group_id: %s", group_id)

    restaurant = _get_restaurant(group_id)
    if not restaurant:
        log.info("Group %s is not in source map", group_id)
        return

    if restaurant.get("skip_images", False):
        log.info("Image skipped for '%s' (skip_images: true)", restaurant["name"])
        return

    if _is_duplicate(event):
        log.info("Duplicate image delivery for group %s — ignored", group_id)
        return

    log.info("Line image from '%s' — queued for download", restaurant["name"])
    _submit(_process_image, restaurant, event.message.id)


# ─────────────────────────────────────────────
#  Postback — Order button interactions
# ─────────────────────────────────────────────
@_handler.add(PostbackEvent)
def handle_postback(event):
    try:
        _handle_postback(event)
    except Exception:
        # An exception here would reach Flask as a 500, which makes Line treat
        # the delivery as failed and redeliver the same postback.
        log.exception("Unhandled error in postback handler")


def _parse_index(raw: str | None) -> int | None:
    """Parse a postback integer; None if missing, non-numeric or negative."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _handle_postback(event):
    try:
        data = dict(pair.split("=", 1) for pair in event.postback.data.split("&"))
    except Exception:
        return

    action      = data.get("action", "")
    user_id     = getattr(event.source, "user_id", None)
    reply_token = event.reply_token

    if not user_id:
        # Happens when the user has not consented to share their ID; without it
        # there is no session key and no DM target.
        log.info("Postback without user_id (action=%s) — ignored", action)
        return

    # A redelivered postback would add the same item to the order twice.
    if _is_duplicate(event):
        log.info("Duplicate postback (action=%s) — ignored", action)
        return

    def _get_line_contact(r_slug: str) -> str:
        for r in load_restaurants():
            if make_slug(r["name"]) == r_slug:
                return r.get("line_contact", "")
        return ""

    # ── User tapped "Order" on a restaurant card ──
    if action == "order":
        r_slug = data.get("r", "")

        # Guard 1: already in the middle of an order (spam / accidental double-tap)
        if order_session.get(user_id):
            send_reply(
                reply_token,
                "⚠️ မှာယူနေဆဲ ရှိပါသည်။\n✅ ပြီးပြီ ကို နှိပ်၍ အရင် ပြီးဆုံးပါ။",
            )
            return

        # Guard 2: only allow ordering from today's menu
        if not is_today(r_slug):
            send_reply(
                reply_token,
                "⚠️ ယနေ့ menu မရောက်သေးပါ။\nမနက် menu ရောက်မှ မှာနိုင်ပါသည်။",
            )
            return

        restaurant_name, items = load_menu(r_slug)

        if not items:
            send_reply(reply_token, "⚠️ ယနေ့ menu မရှိသေးပါ။ နောက်မှ ထပ်ကြည့်ပါ။")
            return

        order_session.start(user_id, r_slug, restaurant_name, items)
        try:
            send_order_start_dm(user_id, r_slug, restaurant_name, items)
            send_reply(reply_token, f"📩 {restaurant_name} ၏ menu ကို DM တွင် ပေးပို့ပြီးပါပြီ။")
        except Exception as exc:
            # The fallback below carries no quick replies, so the user could
            # never advance or close this session — drop it instead of leaving
            # them permanently blocked by the "already ordering" guard.
            order_session.end(user_id)
            log.warning("DM failed for user %s: %s — replying in chat", user_id, exc)
            items_text = "\n".join(items)
            send_reply(
                reply_token,
                f"🍽  {restaurant_name}\n━━━━━━━━━━━━━━━━━━━━\n{items_text}\n\n"
                f"(DM လက်ခံရန် bot ကို friend ထည့်ပါ)",
            )

    # ── User tapped an item → ask quantity ──
    elif action == "select_qty":
        r_slug = data.get("r", "")
        idx = _parse_index(data.get("i"))
        if idx is None:
            return

        # Rejects a stale postback whose index or restaurant does not match the
        # live session, so the lookup below can never go out of range.
        session = order_session.set_pending_item(user_id, idx, r_slug)
        if not session:
            send_reply(reply_token, "⚠️ Session မရှိပါ။ menu card မှ ထပ်ကြိုးစားပါ။")
            return

        item_text = session["all_items"][idx]
        try:
            send_qty_selection_dm(user_id, r_slug, idx, item_text)
        except Exception as exc:
            log.warning("Qty DM failed for %s: %s", user_id, exc)

    # ── User chose a quantity ──
    elif action == "add_item":
        r_slug = data.get("r", "")
        idx = _parse_index(data.get("i"))
        qty = _parse_index(data.get("q"))
        if idx is None or qty is None or not 1 <= qty <= 10:
            return

        session = order_session.confirm_item(user_id, qty, r_slug)
        if not session:
            send_reply(reply_token, "⚠️ Session မရှိပါ။ menu card မှ ထပ်ကြိုးစားပါ။")
            return

        try:
            send_order_update_dm(
                user_id, r_slug, session["selected"], session["all_items"]
            )
        except Exception as exc:
            log.warning("DM update failed for %s: %s", user_id, exc)

    # ── User tapped Done ──
    elif action == "done_order":
        session = order_session.end(user_id)
        if not session or not session["selected"]:
            send_reply(reply_token, "⚠️ မည်သည့် menu မျှ မရွေးချယ်ရသေး။")
            return

        line_contact = _get_line_contact(session["slug"])
        try:
            send_order_summary_dm(user_id, session["name"], session["selected"], line_contact)
        except Exception as exc:
            log.warning("Summary DM failed for %s: %s", user_id, exc)
            lines = [f"• {e['item'].replace('• ','')} x{e['qty']}" for e in session["selected"]]
            send_reply(reply_token, f"✅ {session['name']}\n\n" + "\n".join(lines))
