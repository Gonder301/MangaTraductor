"""End-to-end check of the GUI wiring with a fake OCR model. Skipped where no display exists."""

import time
import tkinter as tk
from types import SimpleNamespace

import pytest
from PIL import Image

from mangatraductor.gui import MangaTranslatorApp


class FakeOCR:
    loaded = True

    def recognize(self, image):
        return "やめろ"


class FakeTranslator:
    def __init__(self, api_key, target_lang):
        self.target_lang = target_lang

    def translate(self, text):
        return "Stop it!"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPL_API_KEY", "test-key")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    instance = MangaTranslatorApp(
        root,
        ocr_engine=FakeOCR(),
        translator_factory=FakeTranslator,
        config_path=tmp_path / "config.json",
        maximize=False,
    )
    yield instance
    root.destroy()


def pump(app, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.root.update()
        if condition():
            return True
        time.sleep(0.02)
    return False


def event(x, y, widget=None):
    return SimpleNamespace(x=x, y=y, widget=widget)


def make_pages(folder, count=2):
    paths = []
    for i in range(count):
        path = folder / f"page{i + 1}.png"
        Image.new("RGB", (400, 600), "white").save(path)
        paths.append(path)
    return paths


def test_select_translate_replace_undo(app, tmp_path):
    page = make_pages(tmp_path, 1)[0]
    app.load_image(page)
    before = app.original_image.tobytes()

    start = (40 * app.scale, 40 * app.scale)
    end = (200 * app.scale, 160 * app.scale)
    app.on_button_press(event(*start))
    app.on_button_release(event(*end))

    def translation():
        return app.txt_translation.get("1.0", "end").strip()

    assert pump(app, lambda: translation() == "Stop it!")
    assert app.txt_ocr.get("1.0", "end").strip() == "やめろ"

    app.replace_text()
    assert app.original_image.tobytes() != before
    app.undo_last_replacement()
    assert app.original_image.tobytes() == before


def test_repeated_bubble_is_served_from_cache(app, tmp_path):
    calls = []

    class CountingTranslator(FakeTranslator):
        def translate(self, text):
            calls.append(text)
            return super().translate(text)

    app.translator_factory = CountingTranslator
    app.load_image(make_pages(tmp_path, 1)[0])

    def log():
        return app.txt_log.get("1.0", "end")

    for _ in range(2):
        app.on_button_press(event(40 * app.scale, 40 * app.scale))
        app.on_button_release(event(200 * app.scale, 160 * app.scale))
        assert pump(app, lambda: "Ready" in app.lbl_status.cget("text"))
        app.txt_translation.delete("1.0", "end")

    assert calls == ["やめろ"]
    assert "Translation (from cache): Stop it!" in log()
    assert (tmp_path / "translations.json").is_file()  # next to the test's config file

    app.clear_translation_cache()
    assert len(app.translation_cache) == 0
    assert "Cleared 1 cached translation(s)." in log()


def test_settings_dialog_clears_the_cache(app):
    app.translation_cache.put("やめろ", "EN-US", None, "Stop it!")
    app.open_settings()
    dialog = next(w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel))
    button = next(
        w for w in dialog.winfo_children()
        if isinstance(w, tk.Button) and w.cget("text").startswith("Clear translation cache")
    )
    assert button.cget("text") == "Clear translation cache (1 saved)"
    button.invoke()
    assert button.cget("text") == "Clear translation cache (0 saved)"
    assert len(app.translation_cache) == 0


def test_navigation_resets_selection(app, tmp_path):
    first, second = make_pages(tmp_path)
    app._scan_folder(first)
    app.load_image(first)
    app.last_box = (0, 0, 10, 10)

    app.next_image()
    assert app.current_path == second
    assert app.last_box is None
    assert "(2/2)" in app.root.title()


def test_letters_typed_in_text_boxes_do_not_trigger_shortcuts(app):
    assert app.is_typing(event(0, 0, widget=app.txt_translation))
    assert not app.is_typing(event(0, 0, widget=app.canvas))


def test_language_choice_is_saved(app, tmp_path):
    app.lang_choice.set("ES - Spanish")
    app._on_language_selected(None)
    assert app.target_lang == "ES"
    assert '"target_lang": "ES"' in (tmp_path / "config.json").read_text(encoding="utf-8")
