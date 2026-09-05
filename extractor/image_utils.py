import base64

import requests


def get_image_url(post: dict) -> str | None:
    try:
        return post["attachments"]["data"][0]["media"]["image"]["src"]
    except (KeyError, IndexError):
        return None


def image_url_to_base64(url: str) -> tuple[str, str]:
    """Download an image and return (base64_data, media_type)."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    encoded = base64.standard_b64encode(response.content).decode("utf-8")
    return encoded, content_type
