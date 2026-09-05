"""gemini_client: retry classification and empty responses. (review findings 2, 10)"""
import types

import pytest
from google.genai import errors as ge

from extractor import gemini_client as gc


def api_error(cls, code, msg):
    return cls(code, {"error": {"message": msg, "status": "S"}})


@pytest.mark.parametrize(
    "exc, retryable",
    [
        # Finding 2: "rate" is a substring of "generateContent", which appears
        # in nearly every google-genai error message.
        (api_error(ge.ClientError, 400, "API key not valid ... :generateContent"), False),
        (api_error(ge.ClientError, 401, "unauthenticated generateContent"), False),
        (api_error(ge.ClientError, 403, "permission denied"), False),
        (api_error(ge.ClientError, 404, "model not found"), False),
        (api_error(ge.ClientError, 429, "quota exceeded"), True),
        (api_error(ge.ServerError, 500, "internal"), True),
        (api_error(ge.ServerError, 503, "model overloaded"), True),
        (AttributeError("'NoneType' has no attribute 'strip' in generate_content"), False),
        (Exception("Deadline_Exceeded while calling"), True),
        (Exception("service unavailable"), True),
    ],
)
def test_retry_classification(exc, retryable):
    assert gc._is_retryable(exc) is retryable


def test_permanent_error_is_not_retried(monkeypatch):
    """A bad API key must fail fast, not sleep through 6 attempts."""
    calls = []

    def boom(**kwargs):
        calls.append(kwargs)
        raise api_error(ge.ClientError, 400, "API key not valid :generateContent")

    monkeypatch.setattr(gc._client.models, "generate_content", boom)
    monkeypatch.setattr(gc.time, "sleep", lambda s: pytest.fail("must not sleep"))

    with pytest.raises(ge.ClientError):
        gc.extract_all_menus([("Fortune", ["some post"])])
    assert len(calls) == 1


def test_transient_error_retries_then_gives_up(monkeypatch):
    calls = []

    def boom(**kwargs):
        calls.append(kwargs)
        raise api_error(ge.ServerError, 503, "overloaded")

    monkeypatch.setattr(gc._client.models, "generate_content", boom)
    monkeypatch.setattr(gc.time, "sleep", lambda s: None)

    assert gc.extract_all_menus([("Fortune", ["some post"])]) is None
    # MAX_RETRIES attempts against each configured model
    assert len(calls) == gc.MAX_RETRIES * len(gc.MODELS)


def test_empty_response_returns_none_instead_of_raising(monkeypatch):
    """Finding 10: response.text is None when a candidate is blocked."""
    response = types.SimpleNamespace(
        text=None,
        candidates=[types.SimpleNamespace(finish_reason="SAFETY")],
        prompt_feedback=None,
    )
    monkeypatch.setattr(gc._client.models, "generate_content", lambda **k: response)
    monkeypatch.setattr(gc.time, "sleep", lambda s: pytest.fail("must not sleep"))

    assert gc.extract_all_menus([("Fortune", ["post"])]) is None
    assert gc.extract_menu_from_image_bytes(b"jpegbytes", "Fortune") is None


def test_not_menu_sentinel_returns_none(monkeypatch):
    response = types.SimpleNamespace(text="NOT_MENU", candidates=[], prompt_feedback=None)
    monkeypatch.setattr(gc._client.models, "generate_content", lambda **k: response)
    assert gc.extract_all_menus([("Fortune", ["hello"])]) is None


def test_menu_response_gets_date_header(monkeypatch):
    response = types.SimpleNamespace(
        text="🍽 Fortune\n📋 menu\n\n• rice", candidates=[], prompt_feedback=None
    )
    monkeypatch.setattr(gc._client.models, "generate_content", lambda **k: response)
    result = gc.extract_all_menus([("Fortune", ["post"])])
    assert result.startswith("🗓")
    assert "• rice" in result
