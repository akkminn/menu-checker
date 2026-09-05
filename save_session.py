"""Run this once to save your Facebook login session for the scraper."""
from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_FILE = Path(__file__).parent / "fb_session.json"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto("https://www.facebook.com/login")

    print("Log in to Facebook in the browser window that just opened.")
    print("After you are fully logged in and see your feed, press ENTER here.")
    input()

    ctx.storage_state(path=str(SESSION_FILE))
    browser.close()
    print(f"Session saved to {SESSION_FILE}")
