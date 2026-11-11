import json
from pathlib import Path

from mangatraductor import config as cfg
from mangatraductor.files import find_images, natural_key


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "nested" / "config.json"
    cfg.save_config({"api_key": "abc", "target_lang": "ES"}, path)
    assert cfg.load_config(path) == {"api_key": "abc", "target_lang": "ES"}


def test_malformed_config_is_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert cfg.load_config(path) == {}


def test_non_object_config_is_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert cfg.load_config(path) == {}


def test_env_var_overrides_saved_key():
    env = {"DEEPL_API_KEY": "from-env"}
    assert cfg.resolve_api_key({"api_key": "from-file"}, env) == "from-env"
    assert cfg.resolve_api_key({"api_key": " from-file "}, {}) == "from-file"
    assert cfg.resolve_api_key({}, {}) == ""


def test_config_path_override():
    path = cfg.default_config_path({"MANGATRADUCTOR_CONFIG": "/tmp/custom.json"})
    assert path == Path("/tmp/custom.json")


def test_legacy_user_config_is_still_read(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGATRADUCTOR_CONFIG", str(tmp_path / "missing" / "config.json"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "user_config.json").write_text(json.dumps({"api_key": "old"}), encoding="utf-8")
    assert cfg.load_config() == {"api_key": "old"}


def test_find_images_natural_order_and_filtering(tmp_path):
    for name in ["page10.png", "page2.PNG", "page1.webp", "notes.txt", "cover.JPG"]:
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "subfolder.png").mkdir()

    names = [p.name for p in find_images(tmp_path)]
    assert names == ["cover.JPG", "page1.webp", "page2.PNG", "page10.png"]


def test_natural_key_orders_numbers_numerically():
    paths = [Path("ch1_p10.png"), Path("ch1_p9.png"), Path("ch1_p100.png")]
    assert [p.name for p in sorted(paths, key=natural_key)] == [
        "ch1_p9.png",
        "ch1_p10.png",
        "ch1_p100.png",
    ]
