from PIL import Image

from mangatraductor.render import (
    block_height,
    canvas_to_image_box,
    draw_translation,
    fit_text,
    load_font,
    text_width,
    wrap_text,
)


class TestCanvasToImageBox:
    def test_scales_back_to_original_pixels(self):
        box = canvas_to_image_box((10, 20), (60, 120), scale=0.5, image_size=(1000, 1000))
        assert box == (20, 40, 120, 240)

    def test_drag_in_any_direction(self):
        forward = canvas_to_image_box((10, 10), (50, 50), 1.0, (100, 100))
        backward = canvas_to_image_box((50, 50), (10, 10), 1.0, (100, 100))
        assert forward == backward == (10, 10, 50, 50)

    def test_tiny_drag_is_ignored(self):
        assert canvas_to_image_box((10, 10), (12, 40), 1.0, (100, 100)) is None

    def test_clamps_to_image_bounds(self):
        assert canvas_to_image_box((-30, -30), (500, 500), 1.0, (100, 80)) == (0, 0, 100, 80)

    def test_selection_outside_image_is_ignored(self):
        assert canvas_to_image_box((200, 200), (300, 300), 1.0, (100, 100)) is None


class TestWrapText:
    def test_lines_fit_width(self):
        font = load_font(20)
        text = "The quick brown fox jumps over the lazy dog again and again"
        lines = wrap_text(text, font, 150)
        assert len(lines) > 1
        assert all(text_width(line, font) <= 150 for line in lines)
        assert " ".join(lines) == text

    def test_keeps_typed_line_breaks(self):
        assert wrap_text("Hello\nworld", load_font(12), 1000) == ["Hello", "world"]

    def test_splits_words_wider_than_the_box(self):
        font = load_font(20)
        lines = wrap_text("Aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!", font, 80)
        assert len(lines) > 1
        assert all(text_width(line, font) <= 80 for line in lines)
        assert "".join(lines) == "Aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!"

    def test_empty_text(self):
        assert wrap_text("   ", load_font(12), 100) == []


class TestFitText:
    def test_result_fits_box(self):
        fitted = fit_text("I can't believe you did that!", 120, 80)
        assert block_height(fitted.lines, fitted.font) <= 80
        assert all(text_width(line, fitted.font) <= 120 for line in fitted.lines)

    def test_prefers_smaller_font_over_breaking_words(self):
        text = "I can't believe you actually did that!"
        fitted = fit_text(text, 160, 240)
        assert " ".join(fitted.lines).split() == text.split()

    def test_breaks_a_word_only_when_nothing_else_fits(self):
        fitted = fit_text("Supercalifragilisticexpialidocious", 90, 90)
        assert len(fitted.lines) > 1
        assert "".join(fitted.lines) == "Supercalifragilisticexpialidocious"
        assert all(text_width(line, fitted.font) <= 90 for line in fitted.lines)

    def test_bigger_box_gets_bigger_font(self):
        small = fit_text("Wait for me!", 60, 40)
        large = fit_text("Wait for me!", 240, 160)
        assert large.size > small.size

    def test_overflow_still_returns_text_at_min_size(self):
        long_text = "This sentence is far too long to ever fit inside such a tiny bubble " * 3
        fitted = fit_text(long_text, 30, 10, min_size=8)
        assert fitted.size == 8
        assert fitted.lines


class TestDrawTranslation:
    def test_paints_only_inside_box(self):
        image = Image.new("RGB", (200, 200), "red")
        box = (50, 50, 150, 120)
        draw_translation(image, box, "Hello!")

        assert image.getpixel((10, 10)) == (255, 0, 0)  # outside: untouched
        assert image.getpixel((190, 190)) == (255, 0, 0)
        inside = image.crop(box).getcolors(maxcolors=100_000)
        colors = {color for _, color in inside}
        assert (255, 255, 255) in colors  # background painted
        assert (255, 0, 0) not in colors  # old content fully covered
        assert any(sum(c) < 200 for c in colors)  # dark text pixels drawn

    def test_returns_font_size_used(self):
        fitted = draw_translation(Image.new("RGB", (300, 300)), (0, 0, 300, 300), "Hi")
        assert fitted.size >= 8
        assert fitted.lines == ["Hi"]
