"""Persistent translation cache, so repeated lines are not sent (and billed) twice.

Translations are stored in ``translations.json`` next to the settings file. The
cache is only an optimisation: if the file cannot be read or written the app
logs a warning and keeps working without it.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from . import config as cfg
from .translate import Translator

logger = logging.getLogger(__name__)

CACHE_FILENAME = "translations.json"
CACHE_VERSION = 1
DEFAULT_MAX_ENTRIES = 20_000  # a few MB at most; the oldest entries are dropped first


def default_cache_path(config_path: Path | None = None) -> Path:
    """Return the cache file path: next to ``config_path`` or the default settings file."""
    settings_file = config_path if config_path is not None else cfg.default_config_path()
    return settings_file.parent / CACHE_FILENAME


def cache_key(text: str, target_lang: str, source_lang: str | None = None) -> str:
    """Build the lookup key. Language codes never contain '|', so keys cannot collide."""
    return f"{(source_lang or 'auto').upper()}|{target_lang.upper()}|{text.strip()}"


class TranslationCache:
    """Thread-safe mapping of (source language, target language, text) to a translation."""

    def __init__(self, path: Path, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self.path = path
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._entries = self._load()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, text: str, target_lang: str, source_lang: str | None = None) -> str | None:
        with self._lock:
            return self._entries.get(cache_key(text, target_lang, source_lang))

    def put(
        self, text: str, target_lang: str, source_lang: str | None, translation: str
    ) -> None:
        """Store a translation and save the file. A failed save is logged, not raised."""
        key = cache_key(text, target_lang, source_lang)
        with self._lock:
            self._entries.pop(key, None)  # re-insert at the end so trimming keeps it
            self._entries[key] = translation
            while len(self._entries) > self.max_entries:
                del self._entries[next(iter(self._entries))]
            # Saving under the lock keeps a slower thread from writing an older snapshot last.
            self._save()

    def clear(self) -> int:
        """Forget every translation and delete the file. Returns how many were removed."""
        with self._lock:
            removed = len(self._entries)
            self._entries.clear()
            try:
                self.path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Could not delete translation cache %s: %s", self.path, exc)
            return removed

    def _load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring unreadable translation cache %s: %s", self.path, exc)
            return {}
        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
            logger.warning("Ignoring translation cache %s: unknown format", self.path)
            return {}
        entries = data.get("translations")
        if not isinstance(entries, dict):
            return {}
        return {k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, str)}

    def _save(self) -> None:
        payload = json.dumps(
            {"version": CACHE_VERSION, "translations": self._entries},
            ensure_ascii=False,
            indent=1,
        )
        tmp_name = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Write a temporary file and swap it in, so a crash never leaves half a file.
            fd, tmp_name = tempfile.mkstemp(
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp_name, self.path)
        except OSError as exc:
            logger.warning("Could not save translation cache %s: %s", self.path, exc)
            if tmp_name is not None:
                Path(tmp_name).unlink(missing_ok=True)


class CachedTranslator:
    """Wrap a translator so each (text, languages) pair is only requested once.

    Failed translations raise as before and are not cached, so they are retried.
    """

    def __init__(
        self,
        inner: Translator,
        cache: TranslationCache,
        target_lang: str,
        source_lang: str | None = None,
    ) -> None:
        self.inner = inner
        self.cache = cache
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.hits = 0
        self.misses = 0

    def translate(self, text: str) -> str:
        if not text.strip():
            return self.inner.translate(text)
        cached = self.cache.get(text, self.target_lang, self.source_lang)
        if cached is not None:
            self.hits += 1
            return cached
        translation = self.inner.translate(text)
        self.misses += 1
        if translation.strip():
            self.cache.put(text, self.target_lang, self.source_lang, translation)
        return translation
