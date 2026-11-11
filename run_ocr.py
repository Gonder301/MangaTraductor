"""Script kept for compatibility: OCR and translate every image in ./images.

Equivalent to `mangatraductor ocr images`, which also accepts other folders,
a target language and an output file (see `mangatraductor ocr --help`).
"""

import sys
from pathlib import Path

from mangatraductor.cli import main

if __name__ == "__main__":
    folder = Path("images")
    if not folder.is_dir():
        folder.mkdir()
        print("Created the 'images' folder. Put cropped speech bubbles in it and run again.")
        sys.exit(0)
    sys.exit(main(["ocr", str(folder)]))
