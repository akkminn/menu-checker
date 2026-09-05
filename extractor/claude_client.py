import anthropic

from extractor.image_utils import image_url_to_base64
from extractor.prompt import IMAGE_PROMPT_TEMPLATE, TEXT_PROMPT_TEMPLATE, today_str
from fetcher.graph_api import get_image_url
from utils.burmese import normalize_burmese

MODEL = "claude-sonnet-4-6"

_client = anthropic.Anthropic()


def extract_menu_from_text(post_text: str) -> str | None:
    normalized = normalize_burmese(post_text)
    prompt = TEXT_PROMPT_TEMPLATE.format(today=today_str(), post_text=normalized)
    response = _client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    result = response.content[0].text.strip()
    return None if result == "NOT_MENU" else result


def extract_menu_from_image(image_url: str) -> str | None:
    image_data, media_type = image_url_to_base64(image_url)
    response = _client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": IMAGE_PROMPT_TEMPLATE.format(today=today_str()),
                },
            ],
        }],
    )
    result = response.content[0].text.strip()
    return None if result == "NOT_MENU" else result


def extract_menu(posts: list[dict]) -> str | None:
    """Try text then image extraction for each post; return first menu found."""
    for post in posts:
        text = post.get("message", "")
        image_url = get_image_url(post)

        if text:
            result = extract_menu_from_text(text)
            if result:
                return result

        if image_url:
            result = extract_menu_from_image(image_url)
            if result:
                return result

    return None
