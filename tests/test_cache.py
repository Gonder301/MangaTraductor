import json
import logging
import threading

import pytest

from mangatraductor.cache import (
    CACHE_FILENAME,
    CachedTranslator,
    TranslationCache,
    default_cache_path,
)
from mangatraductor.translate import TranslationError


class CountingTranslator:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def translate(self, text):
        self.calls.append(text)
        if text == self.fail_on:
            raise TranslationError("quota")
        return "" if not text.strip() else f"<{text}>"


@pytest.fixture
def cache_file(tmp_path):
    return tmp_path / CACHE_FILENAME


def test_cache_lives_next_to_the_settings_file(tmp_path, monkeypatch):
    assert default_cache_path(tmp_path / "custom.json") == tmp_path / CACHE_FILENAME
    monkeypatch.setenv("MANGATRADUCTOR_CONFIG", str(tmp_path / "cfg" / "config.json"))
    assert default_cache_path() == tmp_path / "cfg" / CACHE_FILENAME


def test_translations_persist_across_instances(cache_file):
    TranslationCache(cache_file).put("やめろ", "EN-US", None, "Stop it!")
    assert TranslationCache(cache_file).get("やめろ", "EN-US") == "Stop it!"


def test_languages_are_part_of_the_key(cache_file):
    cache = TranslationCache(cache_file)
    cache.put("やめろ", "EN-US", None, "Stop it!")
    assert cache.get("やめろ", "ES") is None
    assert cache.get("やめろ", "EN-US", source_lang="JA") is None
    assert cache.get("やめろ", "en-us") == "Stop it!"  # codes are case-insensitive


def test_surrounding_whitespace_is_ignored(cache_file):
    cache = TranslationCache(cache_file)
    cache.put(" やめろ\n", "EN-US", None, "Stop it!")
    assert cache.get("やめろ", "EN-US") == "Stop it!"


def test_file_is_readable_json_with_japanese_unescaped(cache_file):
    TranslationCache(cache_file).put("やめろ", "ES", None, "¡Para!")
    raw = cache_file.read_text(encoding="utf-8")
    assert "やめろ" in raw
    assert json.loads(raw) == {"version": 1, "translations": {"AUTO|ES|やめろ": "¡Para!"}}
    assert [p.name for p in cache_file.parent.iterdir()] == [CACHE_FILENAME]  # no temp files


@pytest.mark.parametrize(
    "content",
    ["{not json", "[1, 2]", '{"version": 99, "translations": {}}', '{"version": 1}'],
)
def test_unusable_file_is_ignored_and_then_replaced(cache_file, caplog, content):
    cache_file.write_text(content, encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cache = TranslationCache(cache_file)
    assert len(cache) == 0
    cache.put("やめろ", "EN-US", None, "Stop it!")
    assert TranslationCache(cache_file).get("やめろ", "EN-US") == "Stop it!"


def test_non_string_entries_are_dropped(cache_file):
    cache_file.write_text(
        json.dumps({"version": 1, "translations": {"AUTO|ES|a": "A", "AUTO|ES|b": 3}}),
        encoding="utf-8",
    )
    cache = TranslationCache(cache_file)
    assert len(cache) == 1
    assert cache.get("a", "ES") == "A"


def test_oldest_entries_are_trimmed(cache_file):
    cache = TranslationCache(cache_file, max_entries=2)
    cache.put("one", "ES", None, "uno")
    cache.put("two", "ES", None, "dos")
    cache.put("one", "ES", None, "uno")  # refreshed, so "two" is now the oldest
    cache.put("three", "ES", None, "tres")
    assert cache.get("two", "ES") is None
    assert cache.get("one", "ES") == "uno"
    assert len(TranslationCache(cache_file)) == 2


def test_clear_removes_entries_and_file(cache_file):
    cache = TranslationCache(cache_file)
    cache.put("a", "ES", None, "A")
    cache.put("b", "ES", None, "B")
    assert cache.clear() == 2
    assert len(cache) == 0
    assert not cache_file.exists()
    assert cache.clear() == 0  # clearing an empty cache is fine


def test_save_failure_is_logged_not_raised(tmp_path, caplog):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    cache = TranslationCache(blocker / CACHE_FILENAME)
    with caplog.at_level(logging.WARNING):
        cache.put("やめろ", "EN-US", None, "Stop it!")
    assert "Could not save translation cache" in caplog.text
    assert cache.get("やめろ", "EN-US") == "Stop it!"  # still served from memory


def test_concurrent_puts_keep_the_file_valid(cache_file):
    cache = TranslationCache(cache_file)

    def worker(n):
        for i in range(20):
            cache.put(f"{n}-{i}", "ES", None, str(i))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(TranslationCache(cache_file)) == 80


def test_cached_translator_requests_each_line_once(cache_file):
    inner = CountingTranslator()
    translator = CachedTranslator(inner, TranslationCache(cache_file), "ES")
    assert translator.translate("やめろ") == "<やめろ>"
    assert translator.translate("やめろ") == "<やめろ>"
    assert inner.calls == ["やめろ"]
    assert (translator.hits, translator.misses) == (1, 1)


def test_cached_translator_does_not_cache_failures_or_blank_text(cache_file):
    inner = CountingTranslator(fail_on="やめろ")
    cache = TranslationCache(cache_file)
    translator = CachedTranslator(inner, cache, "ES")
    for _ in range(2):
        with pytest.raises(TranslationError):
            translator.translate("やめろ")
        assert translator.translate("  ") == ""
    assert inner.calls == ["やめろ", "  ", "やめろ", "  "]
    assert len(cache) == 0
