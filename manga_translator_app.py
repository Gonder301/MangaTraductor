import re
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk, ImageDraw, ImageFont
import threading
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
import sys
import os
import requests

# ================= CONFIGURATION =================
CONFIG_FILE = "user_config.json"
FONT_PATH = "font/animeace2_reg.ttf"
# =================================================

def load_config():
    import json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
    return {}

def save_config(api_key):
    import json
    config = {"api_key": api_key}
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f)
    except Exception as e:
        print(f"Error saving config: {e}")

class MangaOCRTranslatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Real-Time Manga OCR & Translator")
        self.root.geometry("1400x900")
        # Try to maximize the window (Windows/Linux)
        try:
            self.root.state('zoomed')  # For Windows
        except:
            self.root.attributes('-zoomed', True)  # For Linux
        
        self.config = load_config()
        self.api_key = self.config.get("api_key", "")
        self.model_loaded = False
        self.processor = None
        self.model = None

        self.original_image = None  # Keeps the full-res loaded image
        self.display_image = None   # The resized image shown on canvas
        self.tk_image = None        # The PhotoImage object for Tkinter
        
        self.scale_factor = 1.0     # Current zoom level (1.0 = 100%)
        
        # Navigation variables
        self.image_list = []
        self.current_image_index = -1
        
        # Selection variables
        self.rect_start_x = None
        self.rect_start_y = None
        self.rect = None
        self.last_crop_coords = None # Store (left, top, right, bottom) of last selection
        self.previous_image_state = None # Store image before replacement for undo

        self._setup_ui()
        self._setup_scrolling_variables() # <--- Initialize Smooth Scrolling
        
        # Start loading model in background
        self.log("Initializing application...")
        threading.Thread(target=self.load_model, daemon=True).start()

    def _setup_scrolling_variables(self):
        """Initializes variables for smooth scrolling acceleration."""
        self.scroll_direction = 0  # 0=Stop, -1=Up, 1=Down
        self.scroll_speed = 0      # Current speed
        self.scroll_job = None     # Timer ID
        
        # Configuration for "Smooth but fast" feel
        self.BASE_SPEED = 1.0      # Starting speed
        self.MAX_SPEED = 40.0      # Maximum speed cap (fast!)
        self.ACCEL_FACTOR = 1    # Multiply speed by this every tick
        self.SCROLL_INTERVAL = 30  # Milliseconds between updates (20ms = ~50 FPS)

        # Bind Key Press (Start moving)
        self.root.bind('<KeyPress-w>', self._start_scroll_up)
        self.root.bind('<KeyPress-s>', self._start_scroll_down)

        # Bind Key Release (Stop moving)
        self.root.bind('<KeyRelease-w>', self._stop_scroll_up)
        self.root.bind('<KeyRelease-s>', self._stop_scroll_down)

    def _setup_ui(self):
        # --- Top Toolbar ---
        toolbar = tk.Frame(self.root, bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        btn_open = tk.Button(toolbar, text="Open Image", command=self.open_image)
        btn_open.pack(side=tk.LEFT, padx=5, pady=5)

        btn_save = tk.Button(toolbar, text="Save Image", command=self.save_image)
        btn_save.pack(side=tk.LEFT, padx=5, pady=5)
        
        # Zoom Controls
        tk.Frame(toolbar, width=20).pack(side=tk.LEFT) # Spacer
        
        btn_zoom_in = tk.Button(toolbar, text="Zoom In (+)", command=self.zoom_in)
        btn_zoom_in.pack(side=tk.LEFT, padx=2)
        
        btn_zoom_out = tk.Button(toolbar, text="Zoom Out (-)", command=self.zoom_out)
        btn_zoom_out.pack(side=tk.LEFT, padx=2)
        
        btn_fit = tk.Button(toolbar, text="Fit Width", command=self.fit_to_width)
        btn_fit.pack(side=tk.LEFT, padx=5)

        tk.Frame(toolbar, width=20).pack(side=tk.LEFT) # Spacer

        # Navigation Controls
        btn_prev = tk.Button(toolbar, text="< Prev (a)", command=self.prev_image)
        btn_prev.pack(side=tk.LEFT, padx=2)
        
        btn_next = tk.Button(toolbar, text="Next > (d)", command=self.next_image)
        btn_next.pack(side=tk.LEFT, padx=2)

        # Basic Navigation Bindings
        self.root.bind('a', lambda event: self.prev_image())
        self.root.bind('d', lambda event: self.next_image())
        self.root.bind("<Left>", lambda e: self.prev_image())
        self.root.bind("<Right>", lambda e: self.next_image())

        tk.Frame(toolbar, width=20).pack(side=tk.LEFT) # Spacer

        btn_settings = tk.Button(toolbar, text="API Key Settings", command=self.open_settings)
        btn_settings.pack(side=tk.LEFT, padx=5, pady=5)
        
        self.lbl_zoom = tk.Label(toolbar, text="Zoom: 100%")
        self.lbl_zoom.pack(side=tk.LEFT, padx=10, pady=5)

        self.lbl_status = tk.Label(toolbar, text="Status: Loading Model...", fg="red")
        self.lbl_status.pack(side=tk.RIGHT, padx=10, pady=5)

        # --- Main Layout (PanedWindow) ---
        paned_window = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True)

        # Left: Image Canvas (Scrollable)
        self.canvas_frame = tk.Frame(paned_window)
        paned_window.add(self.canvas_frame, minsize=800)
        
        # Add scrollbars
        v_scroll = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL)
        h_scroll = tk.Scrollbar(self.canvas_frame, orient=tk.HORIZONTAL)
        
        self.canvas = tk.Canvas(self.canvas_frame, bg="gray", xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)
        
        v_scroll.config(command=self.canvas.yview)
        h_scroll.config(command=self.canvas.xview)
        
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        
        # Mouse Wheel Scrolling
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

        # Right: Results Panel
        right_panel = tk.Frame(paned_window, width=400)
        paned_window.add(right_panel, minsize=300)

        tk.Label(right_panel, text="OCR Output (Japanese)", font=("Arial", 10, "bold")).pack(pady=(10, 0), anchor="w", padx=10)
        self.txt_output_jp = scrolledtext.ScrolledText(right_panel, height=8)
        self.txt_output_jp.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(right_panel, text="Translation (English)", font=("Arial", 10, "bold")).pack(pady=(10, 0), anchor="w", padx=10)
        self.txt_output_en = scrolledtext.ScrolledText(right_panel, height=8)
        self.txt_output_en.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(right_panel, text="Log", font=("Arial", 9, "bold")).pack(pady=(10, 0), anchor="w", padx=10)
        self.txt_log = scrolledtext.ScrolledText(right_panel, height=10, state='disabled', font=("Courier", 8))
        self.txt_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        btn_replace = tk.Button(right_panel, text="Replace Text in Image", command=self.replace_text, bg="lightblue")
        btn_replace.pack(pady=(10, 5), padx=10, fill=tk.X)

        btn_undo = tk.Button(right_panel, text="Undo Last Replacement", command=self.undo_last_replacement)
        btn_undo.pack(pady=(0, 10), padx=10, fill=tk.X)

    def log(self, message):
        self.txt_log.config(state='normal')
        self.txt_log.insert(tk.END, message + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state='disabled')

    # ================= SCROLL LOGIC =================
    def _start_scroll_up(self, event):
        if self.scroll_direction == -1: return # Already moving up
        self.scroll_direction = -1
        self.scroll_speed = self.BASE_SPEED
        self._run_scroll_loop()

    def _start_scroll_down(self, event):
        if self.scroll_direction == 1: return # Already moving down
        self.scroll_direction = 1
        self.scroll_speed = self.BASE_SPEED
        self._run_scroll_loop()

    def _stop_scroll_up(self, event):
        if self.scroll_direction == -1:
            self.scroll_direction = 0

    def _stop_scroll_down(self, event):
        if self.scroll_direction == 1:
            self.scroll_direction = 0

    def _run_scroll_loop(self):
        """The loop that runs every 20ms to scroll and accelerate."""
        if self.scroll_direction == 0:
            return # Stop the loop

        # Perform the scroll
        move_amount = int(self.scroll_speed * self.scroll_direction)
        self.canvas.yview_scroll(move_amount, "units")

        # Accelerate
        if self.scroll_speed < self.MAX_SPEED:
            self.scroll_speed *= self.ACCEL_FACTOR

        # Schedule next run
        if self.scroll_job:
            self.root.after_cancel(self.scroll_job)
        self.scroll_job = self.root.after(self.SCROLL_INTERVAL, self._run_scroll_loop)
    # ================================================

    def load_model(self):
        try:
            model_path = "kha-white/manga-ocr-base"
            self.log(f"Loading model '{model_path}' from Hugging Face Hub... (this may take a moment)")
            
            self.processor = TrOCRProcessor.from_pretrained(model_path)
            self.model = VisionEncoderDecoderModel.from_pretrained(model_path)
            
            self.model_loaded = True
            self.root.after(0, lambda: self.lbl_status.config(text="Status: Ready", fg="green"))
            self.log("Model loaded successfully.")
        except Exception as e:
            self.log(f"Error loading model: {e}")
            self.root.after(0, lambda: self.lbl_status.config(text="Status: Model Error", fg="red"))
            self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to load model:\n{e}"))

    def open_image(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image Files", "*.webp;*.png;*.jpg;*.jpeg;*.bmp")])
        if file_path:
            self.scan_directory(file_path)
            self.load_image(file_path)

    def load_image(self, path):
        try:
            self.original_image = Image.open(path).convert("RGB")
            self.log(f"Loaded image: {os.path.basename(path)}")
            self.fit_to_width()
        except Exception as e:
            self.log(f"Error opening image: {e}")
            messagebox.showerror("Error", f"Could not open image: {e}")

    def scan_directory(self, file_path):
        directory = os.path.dirname(file_path)
        try:
            valid_exts = {".webp", ".png", ".jpg", ".jpeg", ".bmp"}
            all_files = os.listdir(directory)
            self.image_list = []
            for f in all_files:
                ext = os.path.splitext(f)[1].lower()
                if ext in valid_exts:
                    full_path = os.path.join(directory, f)
                    self.image_list.append(full_path)
            
            self.image_list.sort() # Alphabetical order
            
            file_path_norm = os.path.normpath(file_path)
            self.current_image_index = -1
            for i, p in enumerate(self.image_list):
                 if os.path.normpath(p) == file_path_norm:
                      self.current_image_index = i
                      break
            
            self.log(f"Found {len(self.image_list)} images in folder.")
            
        except Exception as e:
            self.log(f"Error scanning directory: {e}")

    def next_image(self):
        if not self.image_list or self.current_image_index == -1: return
        
        new_index = self.current_image_index + 1
        
        if new_index < len(self.image_list):
            self.current_image_index = new_index  # <--- This line was missing!
            self.load_image(self.image_list[new_index])
        else:
            self.log("End of folder.")

    def prev_image(self):
        if not self.image_list or self.current_image_index == -1: return
        
        new_index = self.current_image_index - 1
        
        if new_index >= 0:
            self.current_image_index = new_index  # <--- This line was missing!
            self.load_image(self.image_list[new_index])
        else:
            self.log("Start of folder.")

    def update_display(self):
        if not self.original_image: return

        orig_w, orig_h = self.original_image.size
        new_w = int(orig_w * self.scale_factor)
        new_h = int(orig_h * self.scale_factor)
        
        if new_w <= 0 or new_h <= 0: return

        self.display_image = self.original_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(self.display_image)
        
        self.canvas.config(scrollregion=(0, 0, new_w, new_h))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        
        self.lbl_zoom.config(text=f"Zoom: {int(self.scale_factor * 100)}%")

    def zoom_in(self):
        self.scale_factor *= 1.2
        self.update_display()

    def zoom_out(self):
        self.scale_factor /= 1.2
        self.update_display()

    def fit_to_width(self):
        if not self.original_image: return
        
        canvas_width = self.canvas.winfo_width()
        if canvas_width < 100: canvas_width = 800
        
        orig_w, _ = self.original_image.size
        self.scale_factor = (canvas_width - 20) / orig_w
        self.update_display()

    # --- Scroll Logic (Mouse) ---
    def _bind_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    # --- Mouse Selection Logic ---
    def on_button_press(self, event):
        if not self.original_image: return
        self.rect_start_x = self.canvas.canvasx(event.x)
        self.rect_start_y = self.canvas.canvasy(event.y)
        
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(self.rect_start_x, self.rect_start_y, self.rect_start_x, self.rect_start_y, outline='red', width=2)

    def on_mouse_drag(self, event):
        if not self.rect: return
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect, self.rect_start_x, self.rect_start_y, cur_x, cur_y)

    def on_button_release(self, event):
        if not self.rect or not self.original_image: return
        if not self.model_loaded:
            messagebox.showwarning("Wait", "Model is still loading...")
            return

        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)

        x1, y1 = self.rect_start_x, self.rect_start_y
        x2, y2 = cur_x, cur_y

        left = min(x1, x2)
        top = min(y1, y2)
        right = max(x1, x2)
        bottom = max(y1, y2)

        if right - left < 5 or bottom - top < 5:
            return

        orig_left = int(left / self.scale_factor)
        orig_top = int(top / self.scale_factor)
        orig_right = int(right / self.scale_factor)
        orig_bottom = int(bottom / self.scale_factor)

        w, h = self.original_image.size
        orig_left = max(0, orig_left)
        orig_top = max(0, orig_top)
        orig_right = min(w, orig_right)
        orig_right = min(w, orig_right)
        orig_bottom = min(h, orig_bottom)

        self.last_crop_coords = (orig_left, orig_top, orig_right, orig_bottom)

        crop = self.original_image.crop((orig_left, orig_top, orig_right, orig_bottom))
        
        self.lbl_status.config(text="Status: Processing...", fg="blue")
        threading.Thread(target=self.process_crop, args=(crop,), daemon=True).start()

    def process_crop(self, crop_image):
        try:
            pixel_values = self.processor(images=crop_image, return_tensors="pt").pixel_values
            generated_ids = self.model.generate(pixel_values)
            text_jp = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
            self.root.after(0, lambda: self._update_jp_text(text_jp))
            
            if self.api_key:
                text_en = self.translate_text_api(text_jp)
                self.root.after(0, lambda: self._update_en_text(text_en))
            else:
                self.root.after(0, lambda: self._update_en_text("[No API Key configured]"))
            
            self.root.after(0, lambda: self.lbl_status.config(text="Status: Ready", fg="green"))

        except Exception as e:
            self.log(f"Processing Error: {e}")
            self.root.after(0, lambda: self.lbl_status.config(text="Status: Error", fg="red"))

    def _update_jp_text(self, text):
        self.txt_output_jp.delete(1.0, tk.END)
        self.txt_output_jp.insert(tk.END, text)
        self.log(f"OCR: {text}")

    def _update_en_text(self, text):
        self.txt_output_en.delete(1.0, tk.END)
        self.txt_output_en.insert(tk.END, text)
        self.log(f"Translation: {text}")

    def translate_text_api(self, text):
        if not text.strip(): return ""
        
        url_free = "https://api-free.deepl.com/v2/translate"
        url_pro = "https://api.deepl.com/v2/translate"
        
        url = url_free if self.api_key.endswith(":fx") else url_pro
        
        headers = {
            "Authorization": f"DeepL-Auth-Key {self.api_key}"
        }
        params = {
            "text": text,
            "target_lang": "EN"
        }
        
        try:
            response = requests.post(url, headers=headers, data=params)
            response.raise_for_status()
            return response.json()["translations"][0]["text"]
        except Exception as e:
            return f"Translation Error: {e}"

    def replace_text(self):
        if not self.original_image or not self.last_crop_coords:
            messagebox.showwarning("Warning", "No image loaded or no selection made.")
            return

        text_to_draw = self.txt_output_en.get("1.0", tk.END).strip()
        if not text_to_draw:
            messagebox.showwarning("Warning", "No translated text to replace with.")
            return

        x1, y1, x2, y2 = self.last_crop_coords
        width = x2 - x1
        height = y2 - y1
        
        if width <= 0 or height <= 0: return

        # Save previous state for undo
        self.previous_image_state = self.original_image.copy()

        draw = ImageDraw.Draw(self.original_image)
        
        # 1. Draw white rectangle to cover old text
        draw.rectangle([x1, y1, x2, y2], fill="white", outline="white")

        # 2. Draw new text with adaptive sizing
        def get_font(size):
            try:
                # Check directly in current dir or font subdir as fallback
                if os.path.exists(FONT_PATH):
                    return ImageFont.truetype(FONT_PATH, size)
                elif os.path.exists(os.path.basename(FONT_PATH)):
                     return ImageFont.truetype(os.path.basename(FONT_PATH), size)
                else:
                    return ImageFont.truetype("arial.ttf", size)
            except IOError:
                return ImageFont.load_default()

        # Binary search for best font size
        min_size = 8
        max_size = 200 # Arbitrary upper limit, or could use height
        best_size = min_size
        best_lines = []
        best_font = get_font(min_size)

        low = min_size
        high = max_size

        while low <= high:
            mid = (low + high) // 2
            font_candidate = get_font(mid)
            lines_candidate = self._wrap_text(text_to_draw, font_candidate, width)
            
            # Calculate total height
            total_h = 0
            for line in lines_candidate:
                bbox = draw.textbbox((0, 0), line, font=font_candidate)
                total_h += (bbox[3] - bbox[1]) + 2 # Add padding roughly
            
            if total_h <= height:
                best_size = mid
                best_lines = lines_candidate
                best_font = font_candidate
                low = mid + 1
            else:
                high = mid - 1
        
        # Draw with best found
        current_y = y1
        # Centering vertically if we have space?
        # Let's calculate actual total height of best solution first to center it optionally.
        # For now, just top alignment as per previous impl.
        
        total_content_height = 0
        for line in best_lines:
             bbox = draw.textbbox((0, 0), line, font=best_font)
             total_content_height += (bbox[3] - bbox[1]) + 2
        
        # Optional: Center Vertically
        if total_content_height < height:
             current_y += (height - total_content_height) // 2

        for line in best_lines:
            bbox = draw.textbbox((0, 0), line, font=best_font)
            line_h = bbox[3] - bbox[1]
            
            # Center Horizontally
            line_w = bbox[2] - bbox[0]
            line_x = x1 + (width - line_w) // 2
            
            draw.text((line_x, current_y), line, fill="black", font=best_font)
            current_y += line_h + 2 

        self.update_display()
        self.log(f"Text replaced with font size {best_size}.")

    def _wrap_text(self, text, font, max_width):
        """
        Wraps text to fit within max_width using the given font.
        """
        lines = []
        words = text.split()
        current_line = []
        
        # Create a dummy draw to measure text
        dummy_img = Image.new('RGB', (10, 10))
        draw = ImageDraw.Draw(dummy_img)

        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            w = bbox[2] - bbox[0]
            
            if w <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
            
        return lines



    def undo_last_replacement(self):
        if self.previous_image_state:
            self.original_image = self.previous_image_state
            self.previous_image_state = None # Clear after undoing (single level undo)
            self.update_display()
            self.log("Undo successful.")
        else:
            self.log("Nothing to undo.")
            messagebox.showinfo("Info", "Nothing to undo.")

    def save_image(self):
        if not self.original_image:
            messagebox.showwarning("Warning", "No image loaded to save.")
            return
            
        file_path = filedialog.asksaveasfilename(defaultextension=".webp",
                                                 filetypes=[("WebP", "*.webp"), ("PNG", "*.png"), ("JPEG", "*.jpg"), ("All Files", "*.*")])
        if file_path:
            try:
                self.original_image.save(file_path)
                self.log(f"Image saved to: {file_path}")
                messagebox.showinfo("Success", f"Image saved successfully to:\n{file_path}")
            except Exception as e:
                self.log(f"Error saving image: {e}")
                messagebox.showerror("Error", f"Failed to save image:\n{e}")

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("400x150")
        
        tk.Label(win, text="DeepL API Key:").pack(pady=5)
        entry = tk.Entry(win, width=40)
        entry.pack(pady=5)
        entry.insert(0, self.api_key)
        
        def save():
            self.api_key = entry.get().strip()
            save_config(self.api_key)
            self.log("API Key updated and saved.")
            win.destroy()
            
        tk.Button(win, text="Save", command=save).pack(pady=10)

if __name__ == "__main__":
    root = tk.Tk()
    app = MangaOCRTranslatorApp(root)
    root.mainloop()