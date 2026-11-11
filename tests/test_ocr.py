from mangatraductor.ocr import MangaOCR, postprocess


def test_postprocess_removes_spaces_between_characters():
    assert postprocess("こ ん に ち は") == "こんにちは"


def test_postprocess_normalises_ellipses():
    assert postprocess("え … ？") == "え...？"
    assert postprocess("そ う・・・") == "そう..."


def test_model_is_not_loaded_until_needed():
    # Creating the engine must not download or load the model (no torch needed).
    engine = MangaOCR("some/model")
    assert engine.loaded is False
    assert engine.model_name == "some/model"
