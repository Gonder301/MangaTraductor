from mangatraductor.ocr import MangaOCR, postprocess


def test_postprocess_removes_spaces_between_characters():
    assert postprocess("こ ん に ち は") == "こんにちは"


def test_postprocess_normalises_ellipses():
    assert postprocess("え … ？") == "え...？"
    assert postprocess("そ う・・・") == "そう..."


def test_missing_dependency_inside_model_loading_gives_install_hint(monkeypatch):
    # Simulates transformers being present but the tokenizer's fugashi missing.
    import types

    import pytest

    from mangatraductor.ocr import OCRUnavailableError

    class FailingProcessor:
        @staticmethod
        def from_pretrained(name):
            raise ModuleNotFoundError("You need to install fugashi")

    fake = types.ModuleType("transformers")
    fake.TrOCRProcessor = FailingProcessor
    fake.VisionEncoderDecoderModel = object
    monkeypatch.setitem(__import__("sys").modules, "transformers", fake)

    engine = MangaOCR()
    with pytest.raises(OCRUnavailableError, match=r"fugashi.*\.\[ocr\]"):
        engine.load()
    assert engine.loaded is False


def test_model_is_not_loaded_until_needed():
    # Creating the engine must not download or load the model (no torch needed).
    engine = MangaOCR("some/model")
    assert engine.loaded is False
    assert engine.model_name == "some/model"
