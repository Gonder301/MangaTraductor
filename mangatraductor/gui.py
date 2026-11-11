"""Tkinter desktop app: select a speech bubble, OCR it, translate it, typeset the result."""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any

from PIL import Image, ImageTk

from . import config as cfg
from .cache import CachedTranslator, TranslationCache, default_cache_path
from .files import DIALOG_PATTERN, find_images
from .ocr import MangaOCR, OCREngine
from .render import Box, canvas_to_image_box, draw_translation
from .translate import (
    DEFAULT_TARGET_LANG,
    TARGET_LANGUAGES,
    DeepLTranslator,
    TranslationError,
    Translator,
)

logger = logging.getLogger(__name__)

TranslatorFactory = Callable[[str, str], Translator]  # (api_key, target_lang) -> translator

ZOOM_STEP = 1.2
MAX_UNDO = 20
UI_POLL_MS = 50
# Widgets where letters are typed: single-key shortcuts must not fire there.
TEXT_INPUT_CLASSES = frozenset({"Text", "Entry", "TEntry", "Spinbox", "TSpinbox", "TCombobox"})

# Keyboard scrolling (hold W/S): starts slow and accelerates up to a cap.
SCROLL_BASE_SPEED = 1.0
SCROLL_MAX_SPEED = 40.0
SCROLL_ACCEL = 1.15
SCROLL_INTERVAL_MS = 30


def _default_translator(api_key: str, target_lang: str) -> Translator:
    return DeepLTranslator(api_key, target_lang=target_lang)


class MangaTranslatorApp:
    def __init__(
        self,
        root: tk.Tk,
        ocr_engine: OCREngine | None = None,
        translator_factory: TranslatorFactory = _default_translator,
        config_path: Path | None = None,
        maximize: bool = True,
    ) -> None:
        self.root = root
        self.config_path = config_path
        self.settings: dict[str, Any] = cfg.load_config(config_path)
        self.api_key = cfg.resolve_api_key(self.settings)
        self.target_lang = self.settings.get("target_lang", DEFAULT_TARGET_LANG)
        if self.target_lang not in TARGET_LANGUAGES:
            self.target_lang = DEFAULT_TARGET_LANG
        self.font_path: str | None = self.settings.get("font_path")
        self.ocr = ocr_engine if ocr_engine is not None else MangaOCR()
        self.translator_factory = translator_factory
        self.translation_cache = TranslationCache(default_cache_path(config_path))

        self.original_image: Image.Image | None = None
        self.tk_image: ImageTk.PhotoImage | None = None
        self.scale = 1.0
        self.image_paths: list[Path] = []
        self.current_index = -1
        self.current_path: Path | None = None

        self.selection_start: tuple[float, float] | None = None
        self.selection_rect: int | None = None
        self.last_box: Box | None = None
        self.undo_stack: list[Image.Image] = []
        # Each selection gets a job number; results from older selections are ignored.
        self._job = 0

        self._ui_queue: queue.Queue[tuple[Callable[..., None], tuple[Any, ...]]] = queue.Queue()
        self.scroll_direction = 0
        self.scroll_speed = 0.0
        self._scroll_job: str | None = None

        self.root.title("MangaTraductor")
        self.root.geometry("1400x900")
        if maximize:
            self._maximize()
        self._build_ui()
        self._bind_shortcuts()
        self.root.after(UI_POLL_MS, self._poll_ui_queue)

        if callable(getattr(self.ocr, "load", None)) and not getattr(self.ocr, "loaded", False):
            self.model_ready = False
            self._set_status("Loading OCR model...", "red")
            self.log("Loading OCR model (first run downloads it; this can take a while)...")
            threading.Thread(target=self._load_model, daemon=True).start()
        else:
            self.model_ready = True
            self._set_status("Ready", "green")

    # ------------------------------------------------------------------ setup
    def _maximize(self) -> None:
        try:
            self.root.state("zoomed")  # Windows / macOS
        except tk.TclError:
            try:
                self.root.attributes("-zoomed", True)  # most Linux window managers
            except tk.TclError:
                pass

    def _build_ui(self) -> None:
        toolbar = tk.Frame(self.root, bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        def button(text: str, command: Callable[[], None], padx: int = 2) -> None:
            tk.Button(toolbar, text=text, command=command).pack(side=tk.LEFT, padx=padx, pady=5)

        def spacer() -> None:
            tk.Frame(toolbar, width=20).pack(side=tk.LEFT)

        button("Open Image", self.open_image, padx=5)
        button("Save Image", self.save_image, padx=5)
        spacer()
        button("Zoom In (+)", self.zoom_in)
        button("Zoom Out (-)", self.zoom_out)
        button("Fit Width", self.fit_to_width, padx=5)
        spacer()
        button("< Prev (a)", self.prev_image)
        button("Next > (d)", self.next_image)
        spacer()
        button("API Key Settings", self.open_settings, padx=5)

        tk.Label(toolbar, text="Translate to:").pack(side=tk.LEFT, padx=(10, 2))
        self.lang_choice = ttk.Combobox(
            toolbar,
            state="readonly",
            width=22,
            values=[f"{code} - {name}" for code, name in TARGET_LANGUAGES.items()],
        )
        self.lang_choice.set(f"{self.target_lang} - {TARGET_LANGUAGES[self.target_lang]}")
        self.lang_choice.bind("<<ComboboxSelected>>", self._on_language_selected)
        self.lang_choice.pack(side=tk.LEFT, padx=2)

        self.lbl_zoom = tk.Label(toolbar, text="Zoom: 100%")
        self.lbl_zoom.pack(side=tk.LEFT, padx=10)
        self.lbl_status = tk.Label(toolbar, text="")
        self.lbl_status.pack(side=tk.RIGHT, padx=10)

        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        canvas_frame = tk.Frame(paned)
        paned.add(canvas_frame, minsize=800)
        v_scroll = tk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        h_scroll = tk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        self.canvas = tk.Canvas(
            canvas_frame, bg="gray", xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set
        )
        v_scroll.config(command=self.canvas.yview)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

        panel = tk.Frame(paned, width=400)
        paned.add(panel, minsize=300)

        tk.Label(panel, text="OCR Output (Japanese)", font=("Arial", 10, "bold")).pack(
            pady=(10, 0), anchor="w", padx=10
        )
        self.txt_ocr = scrolledtext.ScrolledText(panel, height=8)
        self.txt_ocr.pack(fill=tk.X, padx=10, pady=5)

        self.lbl_translation = tk.Label(panel, font=("Arial", 10, "bold"))
        self.lbl_translation.pack(pady=(10, 0), anchor="w", padx=10)
        self._update_translation_label()
        self.txt_translation = scrolledtext.ScrolledText(panel, height=8)
        self.txt_translation.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(
            panel,
            text="Tip: you can edit the translation (or type your own) before replacing.",
            fg="gray30",
        ).pack(anchor="w", padx=10)

        tk.Label(panel, text="Log", font=("Arial", 9, "bold")).pack(
            pady=(10, 0), anchor="w", padx=10
        )
        self.txt_log = scrolledtext.ScrolledText(
            panel, height=10, state="disabled", font=("Courier", 8)
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        tk.Button(
            panel, text="Replace Text in Image", command=self.replace_text, bg="lightblue"
        ).pack(pady=(10, 5), padx=10, fill=tk.X)
        tk.Button(panel, text="Undo Last Replacement", command=self.undo_last_replacement).pack(
            pady=(0, 10), padx=10, fill=tk.X
        )

    def _bind_shortcuts(self) -> None:
        shortcuts: dict[str, Callable[[], None]] = {
            "<KeyPress-a>": self.prev_image,
            "<KeyPress-d>": self.next_image,
            "<Left>": self.prev_image,
            "<Right>": self.next_image,
            "<KeyPress-plus>": self.zoom_in,
            "<KeyPress-minus>": self.zoom_out,
            "<Control-z>": self.undo_last_replacement,
            "<Control-s>": self.save_image,
            "<Control-o>": self.open_image,
        }
        for sequence, action in shortcuts.items():
            self.root.bind(sequence, self._shortcut(action))
        self.root.bind("<KeyPress-w>", lambda e: self._start_scroll(e, -1))
        self.root.bind("<KeyPress-s>", lambda e: self._start_scroll(e, 1))
        self.root.bind("<KeyRelease-w>", lambda e: self._stop_scroll(-1))
        self.root.bind("<KeyRelease-s>", lambda e: self._stop_scroll(1))

    def _shortcut(self, action: Callable[[], None]) -> Callable[[tk.Event], str | None]:
        def handler(event: tk.Event) -> str | None:
            if self.is_typing(event):
                return None
            action()
            return "break"

        return handler

    @staticmethod
    def is_typing(event: tk.Event) -> bool:
        """True when the key event comes from a text box, so letters must stay letters."""
        try:
            return event.widget.winfo_class() in TEXT_INPUT_CLASSES
        except (AttributeError, tk.TclError):
            return False

    # ----------------------------------------------------------- thread-safe UI
    def _call_in_ui(self, func: Callable[..., None], *args: Any) -> None:
        """Schedule ``func(*args)`` on the Tk thread. Safe to call from worker threads."""
        self._ui_queue.put((func, args))

    def _poll_ui_queue(self) -> None:
        while True:
            try:
                func, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                func(*args)
            except Exception:  # keep the polling loop alive whatever a callback does
                logger.exception("UI callback failed")
        self.root.after(UI_POLL_MS, self._poll_ui_queue)

    def log(self, message: str) -> None:
        logger.info(message)
        if threading.current_thread() is threading.main_thread():
            self._append_log(message)
        else:
            self._call_in_ui(self._append_log, message)

    def _append_log(self, message: str) -> None:
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, message + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def _set_status(self, text: str, color: str) -> None:
        self.lbl_status.config(text=f"Status: {text}", fg=color)

    # ------------------------------------------------------------------ model
    def _load_model(self) -> None:
        try:
            self.ocr.load()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - worker thread: report any failure in the UI
            message = str(exc)
            self._call_in_ui(self._on_model_failed, message)
            return
        self._call_in_ui(self._on_model_loaded)

    def _on_model_loaded(self) -> None:
        self.model_ready = True
        self._set_status("Ready", "green")
        self.log("OCR model loaded.")

    def _on_model_failed(self, message: str) -> None:
        self._set_status("Model error", "red")
        self.log(f"Error loading OCR model: {message}")
        messagebox.showerror("Error", f"Failed to load the OCR model:\n{message}")

    # ----------------------------------------------------------------- images
    def open_image(self) -> None:
        file_path = filedialog.askopenfilename(filetypes=[("Image files", DIALOG_PATTERN)])
        if not file_path:
            return
        path = Path(file_path)
        self._scan_folder(path)
        self.load_image(path)

    def _scan_folder(self, selected: Path) -> None:
        try:
            self.image_paths = find_images(selected.parent)
        except OSError as exc:
            self.log(f"Error scanning folder: {exc}")
            self.image_paths = [selected]
        resolved = selected.resolve()
        self.current_index = next(
            (i for i, p in enumerate(self.image_paths) if p.resolve() == resolved), -1
        )
        self.log(f"Found {len(self.image_paths)} images in folder.")

    def load_image(self, path: Path) -> None:
        try:
            with Image.open(path) as img:
                image = img.convert("RGB")
        except OSError as exc:
            self.log(f"Error opening image: {exc}")
            messagebox.showerror("Error", f"Could not open image:\n{exc}")
            return
        self.original_image = image
        self.current_path = path
        # A selection or undo history from another page must not leak into this one.
        self.last_box = None
        self.undo_stack.clear()
        self.selection_rect = None
        self._job += 1
        self._update_title()
        self.log(f"Loaded image: {path.name}")
        self.fit_to_width()

    def _update_title(self) -> None:
        if self.current_path is None:
            return
        position = ""
        if self.image_paths and self.current_index >= 0:
            position = f" ({self.current_index + 1}/{len(self.image_paths)})"
        self.root.title(f"MangaTraductor - {self.current_path.name}{position}")

    def next_image(self) -> None:
        self._go_to(self.current_index + 1, "End of folder.")

    def prev_image(self) -> None:
        self._go_to(self.current_index - 1, "Start of folder.")

    def _go_to(self, index: int, edge_message: str) -> None:
        if not self.image_paths or self.current_index == -1:
            return
        if 0 <= index < len(self.image_paths):
            self.current_index = index
            self.load_image(self.image_paths[index])
        else:
            self.log(edge_message)

    def save_image(self) -> None:
        if self.original_image is None:
            messagebox.showwarning("Warning", "No image loaded to save.")
            return
        initial = f"{self.current_path.stem}_translated" if self.current_path else "translated"
        file_path = filedialog.asksaveasfilename(
            defaultextension=".webp",
            initialfile=initial,
            filetypes=[
                ("WebP", "*.webp"),
                ("PNG", "*.png"),
                ("JPEG", "*.jpg"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
            return
        try:
            self.original_image.save(file_path)
        except (OSError, ValueError) as exc:
            self.log(f"Error saving image: {exc}")
            messagebox.showerror("Error", f"Failed to save image:\n{exc}")
            return
        self.log(f"Image saved to: {file_path}")
        messagebox.showinfo("Saved", f"Image saved to:\n{file_path}")

    # ------------------------------------------------------------ zoom / view
    def render(self) -> None:
        if self.original_image is None:
            return
        width, height = self.original_image.size
        new_w, new_h = int(width * self.scale), int(height * self.scale)
        if new_w <= 0 or new_h <= 0:
            return
        display = self.original_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(display)
        self.canvas.config(scrollregion=(0, 0, new_w, new_h))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        self.lbl_zoom.config(text=f"Zoom: {int(self.scale * 100)}%")

    def zoom_in(self) -> None:
        self.scale *= ZOOM_STEP
        self.render()

    def zoom_out(self) -> None:
        self.scale /= ZOOM_STEP
        self.render()

    def fit_to_width(self) -> None:
        if self.original_image is None:
            return
        canvas_width = self.canvas.winfo_width()
        if canvas_width < 100:  # not laid out yet
            canvas_width = 800
        self.scale = (canvas_width - 20) / self.original_image.width
        self.render()

    # -------------------------------------------------------------- scrolling
    def _start_scroll(self, event: tk.Event, direction: int) -> None:
        if self.is_typing(event) or self.scroll_direction == direction:
            return
        self.scroll_direction = direction
        self.scroll_speed = SCROLL_BASE_SPEED
        self._scroll_step()

    def _stop_scroll(self, direction: int) -> None:
        if self.scroll_direction == direction:
            self.scroll_direction = 0

    def _scroll_step(self) -> None:
        if self._scroll_job is not None:
            self.root.after_cancel(self._scroll_job)
            self._scroll_job = None
        if self.scroll_direction == 0:
            return
        self.canvas.yview_scroll(int(self.scroll_speed) * self.scroll_direction, "units")
        self.scroll_speed = min(self.scroll_speed * SCROLL_ACCEL, SCROLL_MAX_SPEED)
        self._scroll_job = self.root.after(SCROLL_INTERVAL_MS, self._scroll_step)

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    def _unbind_mousewheel(self, _event: tk.Event) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(sequence)

    def _on_mousewheel(self, event: tk.Event) -> None:
        # Windows reports multiples of 120 per notch; macOS reports small deltas.
        steps = int(-event.delta / 120) or (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(steps, "units")

    # -------------------------------------------------------------- selection
    def on_button_press(self, event: tk.Event) -> None:
        if self.original_image is None:
            return
        self.selection_start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if self.selection_rect is not None:
            self.canvas.delete(self.selection_rect)
        x, y = self.selection_start
        self.selection_rect = self.canvas.create_rectangle(x, y, x, y, outline="red", width=2)

    def on_mouse_drag(self, event: tk.Event) -> None:
        if self.selection_start is None or self.selection_rect is None:
            return
        x, y = self.selection_start
        self.canvas.coords(
            self.selection_rect, x, y, self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        )

    def on_button_release(self, event: tk.Event) -> None:
        if self.selection_start is None or self.original_image is None:
            return
        end = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        box = canvas_to_image_box(self.selection_start, end, self.scale, self.original_image.size)
        self.selection_start = None
        if box is None:
            return
        if not self.model_ready:
            messagebox.showwarning("Please wait", "The OCR model is still loading...")
            return
        self.last_box = box
        self._job += 1
        crop = self.original_image.crop(box)
        self._set_status("Processing...", "blue")
        threading.Thread(
            target=self._process_crop,
            args=(self._job, crop, self.api_key, self.target_lang),
            daemon=True,
        ).start()

    def _process_crop(self, job: int, crop: Image.Image, api_key: str, target_lang: str) -> None:
        """Worker thread: OCR then translate. Never touches Tk directly."""
        try:
            text = self.ocr.recognize(crop)
        except Exception as exc:  # noqa: BLE001 - worker thread: show the error, don't crash
            self._call_in_ui(self._show_error, job, f"OCR failed: {exc}")
            return
        self._call_in_ui(self._show_ocr_text, job, text)

        if not api_key:
            self._call_in_ui(
                self._show_translation, job, "", "No DeepL API key configured (API Key Settings)."
            )
            return
        translator = CachedTranslator(
            self.translator_factory(api_key, target_lang), self.translation_cache, target_lang
        )
        try:
            translated = translator.translate(text)
        except TranslationError as exc:
            self._call_in_ui(self._show_translation, job, "", str(exc))
            return
        self._call_in_ui(self._show_translation, job, translated, None, translator.hits > 0)

    def _show_ocr_text(self, job: int, text: str) -> None:
        if job != self._job:
            return
        self._set_text(self.txt_ocr, text)
        self._set_text(self.txt_translation, "")
        self.log(f"OCR: {text}")

    def _show_translation(
        self, job: int, text: str, error: str | None, cached: bool = False
    ) -> None:
        if job != self._job:
            return
        self._set_text(self.txt_translation, text)
        if error:
            self._set_status("Translation unavailable", "orange")
            self.log(error)
        else:
            self._set_status("Ready", "green")
            self.log(f"Translation{' (from cache)' if cached else ''}: {text}")

    def _show_error(self, job: int, message: str) -> None:
        if job != self._job:
            return
        self._set_status("Error", "red")
        self.log(message)

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)

    # ---------------------------------------------------------------- editing
    def replace_text(self) -> None:
        if self.original_image is None or self.last_box is None:
            messagebox.showwarning("Warning", "Load an image and select a speech bubble first.")
            return
        text = self.txt_translation.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("Warning", "There is no translated text to draw.")
            return
        self.undo_stack.append(self.original_image.copy())
        del self.undo_stack[:-MAX_UNDO]
        fitted = draw_translation(
            self.original_image, self.last_box, text, font_path=self.font_path
        )
        self.render()
        self.log(f"Text replaced (font size {fitted.size}).")

    def undo_last_replacement(self) -> None:
        if not self.undo_stack:
            self.log("Nothing to undo.")
            return
        self.original_image = self.undo_stack.pop()
        self.render()
        self.log(f"Undo successful ({len(self.undo_stack)} more available).")

    # --------------------------------------------------------------- settings
    def _update_translation_label(self) -> None:
        name = TARGET_LANGUAGES.get(self.target_lang, self.target_lang)
        self.lbl_translation.config(text=f"Translation ({name})")

    def _on_language_selected(self, _event: tk.Event) -> None:
        self.target_lang = self.lang_choice.get().split(" - ", 1)[0]
        self._update_translation_label()
        self._save_settings(target_lang=self.target_lang)
        self.log(f"Target language: {self.target_lang}")

    def _save_settings(self, **changes: Any) -> None:
        self.settings.update(changes)
        try:
            cfg.save_config(self.settings, self.config_path)
        except OSError as exc:
            self.log(f"Could not save settings: {exc}")

    def open_settings(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("DeepL API Key")
        win.geometry("440x220")
        win.transient(self.root)

        tk.Label(win, text="DeepL API Key:").pack(pady=5)
        entry = tk.Entry(win, width=45, show="*")
        entry.pack(pady=5)
        entry.insert(0, self.settings.get("api_key", ""))
        if os.environ.get(cfg.API_KEY_ENV_VAR):
            tk.Label(
                win, text=f"Note: the {cfg.API_KEY_ENV_VAR} environment variable is set and wins.",
                fg="gray30",
            ).pack()

        def save() -> None:
            self._save_settings(api_key=entry.get().strip())
            self.api_key = cfg.resolve_api_key(self.settings)
            self.log("API key saved.")
            win.destroy()

        tk.Button(win, text="Save", command=save).pack(pady=10)

        def cache_label() -> str:
            return f"Clear translation cache ({len(self.translation_cache)} saved)"

        def clear_cache() -> None:
            self.clear_translation_cache()
            clear_button.config(text=cache_label())

        clear_button = tk.Button(win, text=cache_label(), command=clear_cache)
        clear_button.pack()
        entry.focus_set()

    def clear_translation_cache(self) -> None:
        removed = self.translation_cache.clear()
        self.log(f"Cleared {removed} cached translation(s).")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    root = tk.Tk()
    MangaTranslatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
