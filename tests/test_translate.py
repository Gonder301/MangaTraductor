import pytest
import requests

from mangatraductor.translate import (
    FREE_API_URL,
    PRO_API_URL,
    DeepLTranslator,
    TranslationError,
    endpoint_for_key,
    mask_key,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse(payload={"translations": [{"text": "Hello"}]})
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_endpoint_depends_on_key_type():
    assert endpoint_for_key("abc:fx") == FREE_API_URL
    assert endpoint_for_key("abc") == PRO_API_URL


def test_mask_key_hides_most_of_the_key():
    assert mask_key("12345678-aaaa:fx") == "...a:fx"
    assert mask_key("abc") == "****"


def test_successful_translation_sends_expected_request():
    session = FakeSession()
    translator = DeepLTranslator("key:fx", target_lang="ES", session=session, timeout=5)

    assert translator.translate("こんにちは") == "Hello"
    url, kwargs = session.calls[0]
    assert url == FREE_API_URL
    assert kwargs["headers"]["Authorization"] == "DeepL-Auth-Key key:fx"
    assert kwargs["data"] == {"text": "こんにちは", "target_lang": "ES"}
    assert kwargs["timeout"] == 5


def test_source_lang_is_sent_when_given():
    session = FakeSession()
    DeepLTranslator("key", source_lang="JA", session=session).translate("text")
    assert session.calls[0][1]["data"]["source_lang"] == "JA"


def test_empty_text_skips_the_api():
    session = FakeSession()
    assert DeepLTranslator("key", session=session).translate("   ") == ""
    assert session.calls == []


def test_missing_key_raises():
    with pytest.raises(TranslationError, match="No DeepL API key"):
        DeepLTranslator("  ", session=FakeSession()).translate("text")


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, "rejected the API key"), (456, "quota"), (429, "Too many requests"), (500, "HTTP 500")],
)
def test_http_errors_become_readable_messages(status, expected):
    session = FakeSession(response=FakeResponse(status_code=status, text="boom"))
    with pytest.raises(TranslationError, match=expected):
        DeepLTranslator("key", session=session).translate("text")


def test_network_failure_raises_translation_error():
    session = FakeSession(error=requests.ConnectionError("offline"))
    with pytest.raises(TranslationError, match="Could not reach DeepL"):
        DeepLTranslator("key", session=session).translate("text")


def test_unexpected_payload_raises_translation_error():
    session = FakeSession(response=FakeResponse(payload={"unexpected": True}))
    with pytest.raises(TranslationError, match="Unexpected response"):
        DeepLTranslator("key", session=session).translate("text")
