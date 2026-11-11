"""Settings storage and DeepL API key resolution.

Settings live in a per-user file (``%APPDATA%/mangatraductor/config.json`` on
Windows, ``~/.config/mangatraductor/config.json`` elsewhere) so the API key is
never written inside the repository. The ``DEEPL_API_KEY`` environment variable
takes precedence over the file.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_FONT_PATH = PACKAGE_DIR / "fonts" / "animeace2_reg.ttf"

API_KEY_ENV_VAR = "DEEPL_API_KEY"
CONFIG_ENV_VAR = "MANGATRADUCTOR_CONFIG"
# Versions before 0.2 stored the key in ./user_config.json; it is still read as a fallback.
LEGACY_CONFIG_FILE = Path("user_config.json")


def default_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the per-user settings file path (overridable with MANGATRADUCTOR_CONFIG)."""
    env = os.environ if environ is None else environ
    override = env.get(CONFIG_ENV_VAR)
    if override:
        return Path(override)
    if os.name == "nt" and env.get("APPDATA"):
        base = Path(env["APPDATA"])
    else:
        base = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "mangatraductor" / "config.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read settings from ``path``, or from the default and legacy locations.

    Unreadable or malformed files are logged and skipped, never raised, so a
    broken settings file cannot stop the app from starting.
    """
    candidates = [path] if path is not None else [default_config_path(), LEGACY_CONFIG_FILE]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read settings file %s: %s", candidate, exc)
            continue
        if isinstance(data, dict):
            return data
        logger.warning("Ignoring settings file %s: expected a JSON object", candidate)
    return {}


def save_config(settings: Mapping[str, Any], path: Path | None = None) -> Path:
    """Write settings as JSON, creating the parent folder if needed. Returns the path used."""
    target = path if path is not None else default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def resolve_api_key(
    settings: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return the DeepL key: the environment variable first, then the settings file."""
    env = os.environ if environ is None else environ
    from_env = env.get(API_KEY_ENV_VAR, "").strip()
    if from_env:
        return from_env
    source = load_config() if settings is None else settings
    return str(source.get("api_key", "")).strip()
