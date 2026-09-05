from datetime import date, datetime, timezone

import requests

from config import FB_ACCESS_TOKEN

GRAPH_URL = "https://graph.facebook.com/v19.0"


def fetch_today_posts(page_id: str) -> list[dict]:
    url = f"{GRAPH_URL}/{page_id}/posts"
    params = {
        "fields": "message,created_time,attachments{media}",
        "limit": 10,
        "access_token": FB_ACCESS_TOKEN,
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    posts = response.json().get("data", [])
    return _filter_today(posts)


def _filter_today(posts: list[dict]) -> list[dict]:
    today = date.today()
    return [
        p for p in posts
        if datetime.fromisoformat(p["created_time"]).astimezone(timezone.utc).date() == today
    ]


def get_image_url(post: dict) -> str | None:
    try:
        return post["attachments"]["data"][0]["media"]["image"]["src"]
    except (KeyError, IndexError):
        return None
