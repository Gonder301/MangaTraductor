"""Build docs/demo.png: a sample page drawn for the README, before and after MangaTraductor.

The page is generated from scratch (no copyrighted manga). Each speech bubble is
cropped and read by the real OCR model, translated, and typeset with the app's
own renderer, exactly as the desktop app does after you drag a box around it.

    pip install -e ".[ocr]"
    python docs/make_demo.py                 # uses DeepL when a key is configured
    python docs/make_demo.py --no-deepl      # use the reference translations below

Japanese glyphs need a CJK font: Yu Gothic / MS Gothic on Windows, Noto Sans CJK on
Linux, or pass one with --jp-font.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # run from a checkout without installing

from mangatraductor import config as cfg  # noqa: E402
from mangatraductor.cache import CachedTranslator, TranslationCache, default_cache_path  # noqa: E402
from mangatraductor.ocr import MangaOCR  # noqa: E402
from mangatraductor.render import Box, draw_translation  # noqa: E402
from mangatraductor.translate import DeepLTranslator, Translator  # noqa: E402

OUTPUT = ROOT / "docs" / "demo.png"
PAGE_W, PAGE_H = 560, 760
GUTTER = 14
BORDER = 3
JP_SIZE = 30
JP_FONT_CANDIDATES = [
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
]


@dataclass
class Bubble:
    columns: list[str]  # vertical text, read right to left; one entry = horizontal line
    center: tuple[int, int]  # in page coordinates
    tail: tuple[int, int]  # where the tail points to
    reference: str  # translation used when DeepL is not available
    vertical: bool = True
    ocr_box: Box = (0, 0, 0, 0)  # filled in when drawn
    text_box: Box = (0, 0, 0, 0)


BUBBLES = [
    Bubble(["なんだ", "これは！？"], (395, 165), (480, 318), "What is this?!"),
    Bubble(["待って！", "まだ終わって", "ないぞ！"], (150, 545), (45, 732), "Wait! It's not over yet!"),
    Bubble(["よし、", "行くぞ！"], (415, 560), (480, 715), "All right, let's go!", vertical=False),
]


class TranslationService:
    """Pick DeepL (through the cache) when a key is configured, else the references."""

    def __init__(self, use_deepl: bool, target_lang: str) -> None:
        api_key = cfg.resolve_api_key() if use_deepl else ""
        self.deepl: Translator | None = None
        if api_key:
            self.deepl = CachedTranslator(
                DeepLTranslator(api_key, target_lang=target_lang),
                TranslationCache(default_cache_path()),
                target_lang=target_lang,
            )
        self.source = "DeepL" if self.deepl else "reference translations (no DeepL)"

    def translate_bubble(self, text: str, bubble: Bubble) -> str:
        return self.deepl.translate(text) if self.deepl else bubble.reference


def find_jp_font(explicit: str | None) -> str:
    for candidate in [explicit] if explicit else JP_FONT_CANDIDATES:
        try:
            ImageFont.truetype(candidate, JP_SIZE)
            return candidate
        except OSError:
            continue
    raise SystemExit("No Japanese font found; pass one with --jp-font.")


# ------------------------------------------------------------------ page art
def screentone(size: tuple[int, int], spacing: int = 7) -> Image.Image:
    """Dot screentone that fades from dark (bottom) to light (top)."""
    panel = Image.new("L", size, 255)
    draw = ImageDraw.Draw(panel)
    width, height = size
    for row, y in enumerate(range(0, height + spacing, spacing)):
        radius = 0.4 + 2.4 * (y / height)
        offset = spacing / 2 if row % 2 else 0
        for x in range(0, width + spacing, spacing):
            cx = x + offset
            draw.ellipse([cx - radius, y - radius, cx + radius, y + radius], fill=40)
    return panel


def speed_lines(size: tuple[int, int], focus: tuple[int, int], seed: int) -> Image.Image:
    """Radial action lines around ``focus``, leaving the centre clear."""
    rng = random.Random(seed)
    panel = Image.new("L", size, 255)
    draw = ImageDraw.Draw(panel)
    reach = math.hypot(*size)
    for _ in range(170):
        angle = rng.uniform(0, 2 * math.pi)
        start = rng.uniform(0.28, 0.45) * reach
        dx, dy = math.cos(angle), math.sin(angle)
        draw.line(
            [(focus[0] + dx * start, focus[1] + dy * start),
             (focus[0] + dx * reach, focus[1] + dy * reach)],
            fill=0,
            width=rng.choice([1, 1, 2, 3]),
        )
    return panel


def text_block_size(bubble: Bubble, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    step = int(JP_SIZE * 1.12)
    if bubble.vertical:
        return len(bubble.columns) * step, max(len(c) for c in bubble.columns) * step
    width = max(int(font.getlength(line)) for line in bubble.columns)
    return width, len(bubble.columns) * step


def draw_bubble(page: Image.Image, bubble: Bubble, font: ImageFont.FreeTypeFont) -> None:
    """Draw an oval bubble with a tail and its Japanese text; record its boxes."""
    draw = ImageDraw.Draw(page)
    block_w, block_h = text_block_size(bubble, font)
    # Extra side padding keeps tall vertical bubbles from becoming thin slivers.
    pad_x, pad_y = (32, 14) if bubble.vertical else (16, 12)
    # The oval is sized so the padded text block is its inscribed rectangle, so the
    # translation box (that rectangle) covers every Japanese glyph.
    half_w = (block_w / 2 + pad_x) * math.sqrt(2)
    half_h = (block_h / 2 + pad_y) * math.sqrt(2)
    cx, cy = bubble.center
    oval = [cx - half_w, cy - half_h, cx + half_w, cy + half_h]

    # Tail: white wedge over the oval's outline, then its two sides in black.
    draw.ellipse(oval, fill=255, outline=0, width=BORDER)
    tip = bubble.tail
    angle = math.atan2(tip[1] - cy, tip[0] - cx)
    base = [
        (cx + half_w * math.cos(angle + s), cy + half_h * math.sin(angle + s))
        for s in (-0.25, 0.25)
    ]
    inside = [(bx + (bx - tip[0]) * 0.1, by + (by - tip[1]) * 0.1) for bx, by in base]
    draw.polygon([inside[0], tip, inside[1]], fill=255)
    draw.line([base[0], tip], fill=0, width=BORDER)
    draw.line([base[1], tip], fill=0, width=BORDER)

    left, top = cx - block_w / 2, cy - block_h / 2
    step = int(JP_SIZE * 1.12)
    if bubble.vertical:
        for i, column in enumerate(bubble.columns):  # first column is the rightmost
            x = left + block_w - (i + 1) * step + (step - JP_SIZE) / 2
            for j, char in enumerate(column):
                char_w = font.getlength(char)
                draw.text((x + (JP_SIZE - char_w) / 2, top + j * step), char, font=font, fill=0)
    else:
        for i, line in enumerate(bubble.columns):
            draw.text((left, top + i * step), line, font=font, fill=0)

    bubble.ocr_box = tuple(int(v) for v in (oval[0] - 4, oval[1] - 4, oval[2] + 4, oval[3] + 4))
    bubble.text_box = (
        int(cx - block_w / 2 - pad_x), int(cy - block_h / 2 - pad_y),
        int(cx + block_w / 2 + pad_x), int(cy + block_h / 2 + pad_y),
    )


def build_page(jp_font_path: str) -> Image.Image:
    page = Image.new("L", (PAGE_W, PAGE_H), 255)
    draw = ImageDraw.Draw(page)
    m = GUTTER
    top_h = 330
    panels = [
        ((m, m, PAGE_W - m, top_h), screentone((PAGE_W - 2 * m, top_h - m))),
        ((m, top_h + m, PAGE_W // 2 - m // 2, PAGE_H - m),
         speed_lines((PAGE_W // 2 - m // 2 - m, PAGE_H - top_h - 2 * m), (120, 210), seed=3)),
        ((PAGE_W // 2 + m // 2, top_h + m, PAGE_W - m, PAGE_H - m),
         speed_lines((PAGE_W // 2 - m // 2 - m, PAGE_H - top_h - 2 * m), (140, 300), seed=7)),
    ]
    for (x0, y0, x1, y1), art in panels:
        page.paste(art.resize((x1 - x0, y1 - y0)), (x0, y0))
        draw.rectangle([x0, y0, x1, y1], outline=0, width=BORDER)

    font = ImageFont.truetype(jp_font_path, JP_SIZE)
    for bubble in BUBBLES:
        draw_bubble(page, bubble, font)
    return page


# ------------------------------------------------------------------ pipeline
def compose(before: Image.Image, after: Image.Image) -> Image.Image:
    margin, label_h, arrow_w = 24, 44, 60
    width = margin * 2 + PAGE_W * 2 + arrow_w
    height = margin + label_h + PAGE_H + margin
    sheet = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(sheet)
    try:
        label_font = ImageFont.truetype("arialbd.ttf", 24)
    except OSError:
        label_font = ImageFont.load_default(24)
    right_x = margin + PAGE_W + arrow_w
    for x, label in [(margin, "Original"), (right_x, "After MangaTraductor")]:
        text_w = draw.textlength(label, font=label_font)
        draw.text((x + (PAGE_W - text_w) / 2, margin), label, font=label_font, fill=60)
    sheet.paste(before, (margin, margin + label_h))
    sheet.paste(after, (right_x, margin + label_h))
    ay = margin + label_h + PAGE_H // 2
    ax0, ax1 = margin + PAGE_W + 8, right_x - 8
    draw.line([(ax0, ay), (ax1 - 14, ay)], fill=70, width=10)
    draw.polygon([(ax1, ay), (ax1 - 24, ay - 18), (ax1 - 24, ay + 18)], fill=70)
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-deepl", action="store_true", help="use the reference translations")
    parser.add_argument("--target-lang", default="EN-US")
    parser.add_argument("--jp-font", help="font with Japanese glyphs")
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    before = build_page(find_jp_font(args.jp_font))
    after = before.copy()
    ocr = MangaOCR()
    translator = TranslationService(not args.no_deepl, args.target_lang)
    print(f"Translations: {translator.source}")
    for bubble in BUBBLES:
        text = ocr.recognize(before.crop(bubble.ocr_box).convert("RGB"))
        translation = translator.translate_bubble(text, bubble)
        fitted = draw_translation(after, bubble.text_box, translation, background=255, text_color=0)
        print(f"  [JP] {''.join(bubble.columns)}  ->  [OCR] {text}  ->  [EN] {translation}"
              f"  (font {fitted.size}px)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    compose(before, after).save(args.output, optimize=True)
    print(f"Saved {args.output} ({args.output.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
