from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext

from utils.logger import log

SESSION_FILE = Path(__file__).parent.parent / "fb_session.json"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Selectors for full post text on an individual post page
_POST_TEXT_SELECTORS = [
    '[data-ad-preview="message"]',
    'div[data-ad-comet-preview="message"]',
    'div[dir="auto"][style*="text-align"]',
]


def _collect_post_links(page) -> list[str]:
    """Collect individual post permalink URLs from a Facebook page feed."""
    links = set()
    for selector in [
        'a[href*="/posts/"]',
        'a[href*="story_fbid"]',
        'a[href*="permalink.php"]',
    ]:
        for el in page.locator(selector).all():
            href = el.get_attribute("href") or ""
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.facebook.com" + href
            # Strip tracking params from /posts/ URLs
            if "/posts/" in href:
                href = href.split("?")[0]
            links.add(href)
    return list(links)


def _extract_text_from_post_page(ctx: BrowserContext, url: str) -> str:
    """Open an individual post URL and return its full text."""
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2500)

        for selector in _POST_TEXT_SELECTORS:
            blocks = page.locator(selector).all_text_contents()
            blocks = [b.strip() for b in blocks if len(b.strip()) > 20]
            if blocks:
                return "\n".join(blocks)

        # Fallback: grab the largest text block on the page
        all_divs = page.locator("div[dir='auto']").all_text_contents()
        all_divs = [d.strip() for d in all_divs if len(d.strip()) > 40]
        if all_divs:
            return max(all_divs, key=len)

    except Exception as exc:
        log.warning("Could not fetch post %s: %s", url, exc)
    finally:
        page.close()
    return ""


def scrape_today_posts(page_url: str) -> list[str]:
    """Scrape full post text by visiting each individual post page."""
    log.info("Scraping %s", page_url)

    storage_state = str(SESSION_FILE) if SESSION_FILE.exists() else None
    if not storage_state:
        log.warning("No saved session — run save_session.py first")

    texts = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state=storage_state,
            user_agent=_USER_AGENT,
            locale="my-MM",
        )

        # Step 1: load the page feed and collect post links
        feed_page = ctx.new_page()
        feed_page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
        feed_page.wait_for_timeout(3000)
        post_links = _collect_post_links(feed_page)
        feed_page.close()
        log.info("Found %d post link(s)", len(post_links))

        # Step 2: visit each post and get the full text
        for link in post_links[:8]:  # cap at 8 most recent posts
            text = _extract_text_from_post_page(ctx, link)
            if text:
                texts.append(text)

        browser.close()

    log.info("Collected %d full post text(s)", len(texts))
    return texts
