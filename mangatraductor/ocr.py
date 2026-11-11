"""Japanese OCR for manga speech bubbles, using the kha-white/manga-ocr-base model.

The model expects one cropped speech bubble per image, not a full page.
"""

from __future__ import annotations

import re
import threading
from typing import Protocol

from PIL import Image

DEFAULT_MODEL = "kha-white/manga-ocr-base"
# Same limit as the model's own generation config and the manga-ocr reference; passed
# explicitly so a custom --model with a shorter default does not cut long bubbles.
MAX_NEW_TOKENS = 300


class OCRUnavailableError(RuntimeError):
    """The optional OCR dependencies (PyTorch, Transformers) are not installed."""


class OCREngine(Protocol):
    """Anything that turns a cropped speech bubble into text."""

    def recognize(self, image: Image.Image) -> str:
        """Return the text found in ``image``."""
        ...


def postprocess(text: str) -> str:
    """Clean the decoder output.

    The tokenizer decodes Japanese one character per token joined by spaces
    ("こ ん に ち は"), so all whitespace is removed. Runs of dots or "・" become
    plain dots and "…" becomes "...", matching the manga-ocr reference
    post-processing so the translator receives normal punctuation.
    """
    text = "".join(text.split())
    text = text.replace("…", "...")
    return re.sub(r"[・.]{2,}", lambda match: "." * len(match.group()), text)


class MangaOCR:
    """Lazy wrapper around the Hugging Face model.

    Nothing heavy is imported or downloaded until :meth:`load` (or the first
    :meth:`recognize`) runs, so the rest of the package works without torch.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._processor = None
        self._model = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Download (first run only) and load the model. Safe to call from several threads."""
        with self._lock:
            if self._model is not None:
                return
            # Missing optional packages surface as ImportError either here or inside
            # from_pretrained (e.g. the tokenizer needs fugashi), so both are covered.
            try:
                from transformers import TrOCRProcessor, VisionEncoderDecoderModel

                processor = TrOCRProcessor.from_pretrained(self.model_name)
                model = VisionEncoderDecoderModel.from_pretrained(self.model_name)
            except ImportError as exc:
                raise OCRUnavailableError(
                    f"Missing OCR dependency ({exc}). Install them with: "
                    'pip install -e ".[ocr]"'
                ) from exc
            self._processor = processor
            self._model = model

    def recognize(self, image: Image.Image) -> str:
        self.load()
        inputs = self._processor(images=image.convert("RGB"), return_tensors="pt")
        pixel_values = inputs.pixel_values
        generated_ids = self._model.generate(pixel_values, max_length=MAX_NEW_TOKENS)
        raw = self._processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return postprocess(raw)
