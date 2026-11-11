"""DeepL translation client with clear, user-facing error messages."""

from __future__ import annotations

from typing import Protocol

import requests

FREE_API_URL = "https://api-free.deepl.com/v2/translate"
PRO_API_URL = "https://api.deepl.com/v2/translate"
DEFAULT_TIMEOUT = 15.0  # seconds; without a timeout a stalled request blocks forever
DEFAULT_TARGET_LANG = "EN-US"

# Target languages offered in the GUI (DeepL codes -> display names).
TARGET_LANGUAGES = {
    "EN-US": "English (US)",
    "EN-GB": "English (UK)",
    "ES": "Spanish",
    "PT-BR": "Portuguese (Brazil)",
    "FR": "French",
    "DE": "German",
    "IT": "Italian",
}

_STATUS_MESSAGES = {
    403: "DeepL rejected the API key (HTTP 403). Check it in API Key Settings.",
    429: "Too many requests to DeepL (HTTP 429). Wait a moment and try again.",
    456: "Your DeepL character quota is used up (HTTP 456).",
}


class TranslationError(RuntimeError):
    """Raised when a translation cannot be produced. The message is safe to show users."""


class Translator(Protocol):
    def translate(self, text: str) -> str:
        """Return ``text`` translated; raise TranslationError on failure."""
        ...


def endpoint_for_key(api_key: str) -> str:
    """DeepL Free keys end in ':fx' and must use the free endpoint."""
    return FREE_API_URL if api_key.strip().endswith(":fx") else PRO_API_URL


def mask_key(api_key: str) -> str:
    """Show only the last 4 characters of a key, for logs and diagnostics."""
    return f"...{api_key[-4:]}" if len(api_key) > 4 else "****"


class DeepLTranslator:
    def __init__(
        self,
        api_key: str,
        target_lang: str = DEFAULT_TARGET_LANG,
        source_lang: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.timeout = timeout
        self._session = session if session is not None else requests.Session()

    def translate(self, text: str) -> str:
        """Translate ``text``; empty input returns "" without calling the API."""
        if not text.strip():
            return ""
        if not self.api_key:
            raise TranslationError("No DeepL API key configured.")

        data = {"text": text, "target_lang": self.target_lang}
        if self.source_lang:
            data["source_lang"] = self.source_lang
        try:
            response = self._session.post(
                endpoint_for_key(self.api_key),
                headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
                data=data,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TranslationError(f"Could not reach DeepL: {exc}") from exc

        if response.status_code != 200:
            message = _STATUS_MESSAGES.get(
                response.status_code,
                f"DeepL returned HTTP {response.status_code}: {response.text[:200]}",
            )
            raise TranslationError(message)
        try:
            return response.json()["translations"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise TranslationError("Unexpected response format from DeepL.") from exc
