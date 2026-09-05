from datetime import date


def today_str() -> str:
    return date.today().strftime("%A, %B %d, %Y")


def today_short() -> str:
    return date.today().strftime("%d %b %Y")


# ─────────────────────────────────────────────
#  Prompt for batch (Facebook / multi-restaurant)
# ─────────────────────────────────────────────
COMBINED_PROMPT_TEMPLATE = """\
You are a helper that reads Facebook posts from Myanmar restaurants.

Today is {today}.

Below are today's Facebook posts grouped by restaurant. For each restaurant, extract the menu items if found. If a restaurant has no menu post today, skip it entirely.

Format EACH restaurant section EXACTLY like this — use the exact symbols shown:

🍽 [RESTAURANT_NAME]
━━━━━━━━━━━━━━━━━━━━
📋 ရရှိနိုင်သော menu များ

• [menu item 1]
• [menu item 2]
• [menu item 3]

If a menu item has a price, put it after the item: • ကြက်ဟင်းခါး - 50 ฿

Separate multiple restaurant sections with:
────────────────────────

If NO restaurant has a menu today, reply with exactly: NOT_MENU

{restaurant_blocks}

Respond only with the formatted sections or NOT_MENU."""


# ─────────────────────────────────────────────
#  Prompt for single image (Line image message)
# ─────────────────────────────────────────────
IMAGE_MENU_PROMPT_TEMPLATE = """\
Today is {today}. This image is from a Line group of a Myanmar restaurant called '{restaurant_name}'.
If it shows a menu or food items available today, extract all items and prices (if shown).
Format the items as a simple list, one item per line, with price after a dash if available.
Example:
ကြက်ဟင်းခါး - 50 ฿
ငါးချဉ်ဟင်း
If it is not a menu image, reply with exactly: NOT_MENU"""


def build_restaurant_block(name: str, posts: list[str]) -> str:
    joined = "\n---\n".join(posts) if posts else "(no posts found)"
    return f"Restaurant: {name}\nPosts:\n{joined}"


def format_image_menu_message(restaurant_name: str, menu_items: str) -> str:
    """Wrap raw image-extracted menu items in the standard visual format."""
    lines = [f"• {line.strip()}" if not line.strip().startswith("•") else line.strip()
             for line in menu_items.splitlines() if line.strip()]
    items = "\n".join(lines)
    return (
        f"🍽 {restaurant_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 ရရှိနိုင်သော menu များ\n\n"
        f"{items}"
    )


def format_batch_header() -> str:
    """Date header prepended to the Facebook batch message."""
    return f"🗓 {today_short()} နေ့ menu များ\n\n"
