import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from mangatraductor import cli
from mangatraductor.ocr import OCRUnavailableError
from mangatraductor.translate import TranslationError


class FakeOCR:
    def __init__(self, model_name="fake"):
        self.model_name = model_name

    def recognize(self, image):
        return f"テキスト{image.width}"


class FakeTranslator:
    def __init__(self, api_key, target_lang="EN-US", source_lang=None):
        self.target_lang = target_lang

    def translate(self, text):
        if text == "テキスト13":
            raise TranslationError("quota")
        return f"{self.target_lang}:{text}"


@pytest.fixture
def bubbles(tmp_path):
    folder = tmp_path / "bubbles"
    folder.mkdir()
    for width, name in [(10, "b10.png"), (11, "b2.png"), (12, "b1.jpg")]:
        Image.new("RGB", (width, 5)).save(folder / name)
    (folder / "readme.txt").write_text("not an image")
    return folder


@pytest.fixture(autouse=True)
def isolated_key(monkeypatch, tmp_path):
    monkeypatch.setenv("MANGATRADUCTOR_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("DEEPL_API_KEY", "test-key:fx")
    monkeypatch.chdir(tmp_path)


def run(argv):
    return cli.main(argv, ocr_factory=FakeOCR, translator_factory=FakeTranslator)


def test_folder_to_json(bubbles, tmp_path):
    out = tmp_path / "out.json"
    assert run(["ocr", str(bubbles), "-t", "ES", "-o", str(out)]) == 0
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert [Path(r["image"]).name for r in rows] == ["b1.jpg", "b2.png", "b10.png"]
    assert rows[0]["text"] == "テキスト12"
    assert rows[0]["translation"] == "ES:テキスト12"


def test_csv_output_is_excel_friendly(bubbles, tmp_path):
    out = tmp_path / "out.csv"
    run(["ocr", str(bubbles), "-o", str(out)])
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    assert len(rows) == 3


def test_no_translate_skips_translation(bubbles, tmp_path):
    out = tmp_path / "out.json"
    run(["ocr", str(bubbles), "--no-translate", "-o", str(out)])
    assert all(r["translation"] is None for r in json.loads(out.read_text(encoding="utf-8")))


def test_errors_are_recorded_and_batch_continues(tmp_path):
    Image.new("RGB", (13, 5)).save(tmp_path / "quota.png")
    (tmp_path / "broken.png").write_bytes(b"not really a png")
    out = tmp_path / "out.json"
    paths = [str(tmp_path / "quota.png"), str(tmp_path / "broken.png")]
    assert run(["ocr", *paths, "-o", str(out)]) == 1
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert rows[0]["error"] == "quota"
    assert rows[1]["error"].startswith("OCR failed")


def test_missing_paths_exit_with_usage_error(tmp_path, capsys):
    assert run(["ocr", str(tmp_path / "nope")]) == 2
    assert "Not found" in capsys.readouterr().err


def test_bad_output_extension_is_rejected(bubbles, tmp_path):
    assert run(["ocr", str(bubbles), "-o", str(tmp_path / "out.txt")]) == 2


def test_missing_ocr_dependencies_fail_once_with_install_hint(bubbles, capsys):
    class UninstalledOCR(FakeOCR):
        def load(self):
            raise OCRUnavailableError('pip install -e ".[ocr]"')

    code = cli.main(["ocr", str(bubbles)], ocr_factory=UninstalledOCR)
    assert code == 1
    assert '.[ocr]' in capsys.readouterr().err


def test_check_key_success(capsys):
    assert run(["check-key"]) == 0
    output = capsys.readouterr().out
    assert "OK" in output
    assert "test-key" not in output  # the key itself is never printed


def test_check_key_without_key(monkeypatch, capsys):
    monkeypatch.delenv("DEEPL_API_KEY")
    assert run(["check-key"]) == 1
    assert "No DeepL API key" in capsys.readouterr().out
