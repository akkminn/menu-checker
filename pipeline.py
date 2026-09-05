from collections import defaultdict

from config import load_restaurants
from extractor.gemini_client import extract_all_menus
from fetcher.scraper import scrape_today_posts
from sender.line_client import send_to_line, parse_menu_message
from utils.menu_store import save_menu
from utils.logger import log


def run_pipeline() -> None:
    restaurants = load_restaurants()

    # Step 1 — Fetch all posts (scraping only, no AI yet)
    # Group by line_group_id so restaurants sharing a group are batched together
    groups: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)

    for restaurant in restaurants:
        name = restaurant["name"]
        group_id = restaurant["line_group_id"]
        try:
            log.info("Fetching posts for: %s", name)
            texts = scrape_today_posts(restaurant["page_url"])
            groups[group_id].append((name, texts))
            log.info("  → %d text block(s) found", len(texts))
        except Exception as exc:
            log.error("Failed to fetch posts for %s: %s", name, exc)

    # Step 2 — One AI call per Line group, then send
    for group_id, restaurants_posts in groups.items():
        try:
            log.info(
                "Sending %d restaurant(s) to AI for group %s",
                len(restaurants_posts),
                group_id,
            )
            menu_message = extract_all_menus(restaurants_posts)

            if menu_message:
                # Persist items so the Order button can look them up
                _, parsed = parse_menu_message(menu_message)
                for name, items in parsed:
                    save_menu(name, items)

                send_to_line(group_id, menu_message)
                log.info("Menu sent to group %s", group_id)
            else:
                log.warning("No menu found for any restaurant in group %s", group_id)
        except Exception as exc:
            log.error("Failed to send to group %s: %s", group_id, exc)
