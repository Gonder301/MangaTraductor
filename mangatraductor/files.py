"""Finding image files and ordering them the way a reader expects."""

from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_EXTENSIONS = frozenset({".webp", ".png", ".jpg", ".jpeg", ".bmp"})

# Pattern for Tk file dialogs, e.g. "*.bmp *.jpeg *.jpg *.png *.webp".
DIALOG_PATTERN = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))


def is_image(path: Path) -> bool:
    """True if the file extension is one the app can open (case-insensitive)."""
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def natural_key(path: Path) -> list[str | int]:
    """Sort key that orders numbers numerically: page2 comes before page10."""
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def find_images(folder: Path) -> list[Path]:
    """List the supported images directly inside ``folder``, in natural order."""
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and is_image(p)),
        key=natural_key,
    )
