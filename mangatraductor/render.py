"""Pure image helpers: map a canvas selection to the image, fit text in a box, draw it.

Nothing here depends on Tkinter, so it is fully unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .config import DEFAULT_FONT_PATH

# (left, top, right, bottom) in image pixels; right and bottom are exclusive.
Box = tuple[int, int, int, int]
Font = ImageFont.FreeTypeFont | ImageFont.ImageFont

MIN_SELECTION_PX = 5  # drags smaller than this (on screen) are treated as clicks
LINE_SPACING = 2
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 200

_MEASURE = ImageDraw.Draw(Image.new("RGB", (1, 1)))


@dataclass(frozen=True)
class FittedText:
    size: int
    font: Font
    lines: list[str]


def canvas_to_image_box(
    start: tuple[float, float],
    end: tuple[float, float],
    scale: float,
    image_size: tuple[int, int],
) -> Box | None:
    """Convert a drag on the zoomed canvas into a clamped box on the original image.

    Works for drags in any direction. Returns None for tiny drags or boxes
    that fall entirely outside the image.
    """
    (x1, y1), (x2, y2) = start, end
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    if right - left < MIN_SELECTION_PX or bottom - top < MIN_SELECTION_PX:
        return None
    width, height = image_size
    box = (
        max(0, int(left / scale)),
        max(0, int(top / scale)),
        min(width, int(right / scale)),
        min(height, int(bottom / scale)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


@lru_cache(maxsize=256)
def load_font(size: int, font_path: str | None = None) -> Font:
    """Load ``font_path`` at ``size``, falling back to the bundled font, then system fonts."""
    candidates = [font_path] if font_path else []
    candidates += [str(DEFAULT_FONT_PATH), "arial.ttf", "DejaVuSans.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def text_width(text: str, font: Font) -> int:
    left, _, right, _ = _MEASURE.textbbox((0, 0), text, font=font)
    return right - left


def line_height(font: Font) -> int:
    """Constant line height from font metrics, so every line is spaced evenly."""
    try:
        ascent, descent = font.getmetrics()
        return ascent + descent
    except AttributeError:
        _, top, _, bottom = font.getbbox("Ag")
        return bottom - top


def block_height(lines: list[str], font: Font) -> int:
    if not lines:
        return 0
    return len(lines) * line_height(font) + (len(lines) - 1) * LINE_SPACING


def _split_long_word(word: str, font: Font, max_width: int) -> list[str]:
    """Break a word wider than the box into character chunks that each fit."""
    pieces: list[str] = []
    current = ""
    for char in word:
        if current and text_width(current + char, font) > max_width:
            pieces.append(current)
            current = char
        else:
            current += char
    if current:
        pieces.append(current)
    return pieces


def wrap_text(
    text: str, font: Font, max_width: int, split_long_words: bool = True
) -> list[str]:
    """Greedy word wrap that keeps line breaks the user typed.

    Words wider than ``max_width`` are split into chunks, unless
    ``split_long_words`` is False (then they stay whole and overflow).
    """
    lines: list[str] = []
    for paragraph in text.splitlines():
        current: list[str] = []
        for word in paragraph.split():
            if not split_long_words or text_width(word, font) <= max_width:
                pieces = [word]
            else:
                pieces = _split_long_word(word, font, max_width)
            for piece in pieces:
                if current and text_width(" ".join([*current, piece]), font) > max_width:
                    lines.append(" ".join(current))
                    current = [piece]
                else:
                    current.append(piece)
        if current:
            lines.append(" ".join(current))
    return lines


def fit_text(
    text: str,
    box_width: int,
    box_height: int,
    font_path: str | None = None,
    min_size: int = MIN_FONT_SIZE,
    max_size: int = MAX_FONT_SIZE,
) -> FittedText:
    """Binary-search the largest font size whose wrapped text fits the box.

    Sizes that keep every word whole are preferred; words are only broken when
    no size fits otherwise (e.g. one very long word in a narrow bubble). If even
    ``min_size`` overflows, the text is still returned at ``min_size``: a
    slightly overflowing translation is better than an erased, empty bubble.
    """
    high = max(min_size, min(max_size, box_height))
    best = _largest_fitting_size(text, box_width, box_height, font_path, min_size, high, False)
    if best is None:
        best = _largest_fitting_size(text, box_width, box_height, font_path, min_size, high, True)
    if best is None:
        font = load_font(min_size, font_path)
        best = FittedText(min_size, font, wrap_text(text, font, box_width))
    return best


def _largest_fitting_size(
    text: str,
    box_width: int,
    box_height: int,
    font_path: str | None,
    low: int,
    high: int,
    split_long_words: bool,
) -> FittedText | None:
    best: FittedText | None = None
    while low <= high:
        mid = (low + high) // 2
        font = load_font(mid, font_path)
        lines = wrap_text(text, font, box_width, split_long_words)
        fits = block_height(lines, font) <= box_height and all(
            text_width(line, font) <= box_width for line in lines
        )
        if fits:
            best = FittedText(mid, font, lines)
            low = mid + 1
        else:
            high = mid - 1
    return best


def draw_translation(
    image: Image.Image,
    box: Box,
    text: str,
    font_path: str | None = None,
    text_color: str = "black",
    background: str = "white",
) -> FittedText:
    """Cover ``box`` with ``background`` and draw ``text`` centred inside it (in place)."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise ValueError(f"Empty box: {box}")

    fitted = fit_text(text, width, height, font_path)
    draw = ImageDraw.Draw(image)
    draw.rectangle([left, top, right, bottom], fill=background)

    step = line_height(fitted.font) + LINE_SPACING
    y = top + max(0, (height - block_height(fitted.lines, fitted.font)) // 2)
    for line in fitted.lines:
        bbox_left, _, bbox_right, _ = draw.textbbox((0, 0), line, font=fitted.font)
        x = left + (width - (bbox_right - bbox_left)) // 2 - bbox_left
        draw.text((x, y), line, fill=text_color, font=fitted.font)
        y += step
    return fitted
