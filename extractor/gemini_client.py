import time

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from extractor.prompt import (
    COMBINED_PROMPT_TEMPLATE,
    IMAGE_MENU_PROMPT_TEMPLATE,
    build_restaurant_block,
    format_batch_header,
    format_image_menu_message,
    today_str,
)
from utils.burmese import normalize_burmese
from utils.logger import log
from config import GOOGLE_API_KEY

# Try primary model first, fall back to secondary if unavailable
MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]
MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds between retries

_client = genai.Client(api_key=GOOGLE_API_KEY)


# HTTP statuses worth retrying; anything else (401, 400, 404…) is permanent.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# Matched against the error text only as a fallback when no status is exposed.
# Keep these specific: a bare "rate" also matches "generateContent", which
# appears in almost every google-genai error message.
_RETRYABLE_PHRASES = (
    "unavailable",
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "deadline_exceeded",
    "too many requests",
    "internal error",
)


def _is_retryable(exc: Exception) -> bool:
    """Return True for transient errors worth retrying (5xx, rate limits)."""
    if isinstance(exc, genai_errors.ServerError):
        return True
    status = getattr(exc, "code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        # A status we can trust — don't second-guess it with text matching.
        return status in _RETRYABLE_STATUS
    msg = str(exc).lower()
    return any(phrase in msg for phrase in _RETRYABLE_PHRASES)


def _response_text(response) -> str | None:
    """Return the response text, or None if the model produced none.

    response.text is None when the candidate was blocked or truncated
    (safety filter, MAX_TOKENS). Dereferencing it raises AttributeError,
    which would otherwise discard every restaurant batched into the call.
    """
    text = getattr(response, "text", None)
    if text:
        return text.strip()

    reasons = []
    for candidate in getattr(response, "candidates", None) or []:
        reason = getattr(candidate, "finish_reason", None)
        if reason:
            reasons.append(str(reason))
    log.error(
        "Model returned no text (finish_reason=%s, prompt_feedback=%s)",
        reasons or "unknown",
        getattr(response, "prompt_feedback", None),
    )
    return None


def extract_all_menus(restaurants_posts: list[tuple[str, list[str]]]) -> str | None:
    """Send all restaurants' posts in one AI call.

    Args:
        restaurants_posts: list of (restaurant_name, [post_text, ...])

    Returns:
        Formatted menu string for all restaurants, or None if nothing found.
    """
    blocks = []
    for name, posts in restaurants_posts:
        normalized = [normalize_burmese(p) for p in posts]
        blocks.append(build_restaurant_block(name, normalized))

    restaurant_blocks = "\n\n".join(blocks)
    prompt = COMBINED_PROMPT_TEMPLATE.format(
        today=today_str(),
        restaurant_blocks=restaurant_blocks,
    )

    for model in MODELS:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log.info("Calling AI model: %s (attempt %d)", model, attempt)
                response = _client.models.generate_content(model=model, contents=prompt)
                result = _response_text(response)
                if result is None:
                    # Blocked or truncated — a retry of the same prompt will not
                    # help, so report "no menu" rather than crashing the batch.
                    return None
                if result == "NOT_MENU":
                    return None
                return format_batch_header() + result
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                log.warning("Model %s unavailable (attempt %d/%d): %s", model, attempt, MAX_RETRIES, exc)
                if attempt < MAX_RETRIES:
                    log.info("Retrying in %ds...", RETRY_DELAY)
                    time.sleep(RETRY_DELAY)
        log.warning("All retries exhausted for %s — trying next model", model)

    log.error("All models failed. No menu extracted.")
    return None


def extract_menu_from_image_bytes(image_bytes: bytes, restaurant_name: str) -> str | None:
    """Extract menu from raw image bytes (used for Line image messages)."""
    # Detect image type from magic bytes
    media_type = "image/jpeg"
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        media_type = "image/png"
    elif image_bytes[:4] == b'GIF8':
        media_type = "image/gif"

    prompt = IMAGE_MENU_PROMPT_TEMPLATE.format(
        today=today_str(),
        restaurant_name=restaurant_name,
    )

    for model in MODELS:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log.info("Calling AI (image) model: %s (attempt %d)", model, attempt)
                response = _client.models.generate_content(
                    model=model,
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                        prompt,
                    ],
                )
                result = _response_text(response)
                if result is None:
                    return None
                if result == "NOT_MENU":
                    return None
                return format_image_menu_message(restaurant_name, result)
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                log.warning("Model %s unavailable (attempt %d/%d): %s", model, attempt, MAX_RETRIES, exc)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
        log.warning("All retries exhausted for %s — trying next model", model)

    log.error("All models failed for image extraction.")
    return None
