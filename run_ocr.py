import torch
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
from PIL import Image
import sys
import os
import requests
import glob

# ================= CONFIGURATION =================
# Load API Key from user_config.json if available
import json
CONFIG_FILE = "user_config.json"
API_KEY = ""

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            API_KEY = config.get("api_key", "")
    except:
        pass

if not API_KEY:
    # Fallback or placeholder
    API_KEY = "YOUR_DEEPL_API_KEY"

# Folder containing images to translate
IMAGE_FOLDER = "images"

# DeepL API URLs
URL_FREE = "https://api-free.deepl.com/v2/translate"
URL_PRO = "https://api.deepl.com/v2/translate"
# =================================================

def translate_text(text, api_key):
    """
    Translates text using DeepL API.
    """
    if not api_key or "YOUR_DEEPL_API_KEY" in api_key:
        return "[Skipped] No valid API Key provided in code."

    # Heuristic: deepL keys usually end in :fx for free accounts
    if api_key.endswith(":fx"):
        url = URL_FREE
    else:
        url = URL_PRO

    headers = {
        "Authorization": f"DeepL-Auth-Key {api_key}"
    }
    params = {
        "text": text,
        "target_lang": "EN"
    }

    try:
        response = requests.post(url, headers=headers, data=params)
        response.raise_for_status()
        result = response.json()
        return result["translations"][0]["text"]
    except requests.exceptions.RequestException as e:
        return f"Error translating: {e}"

def main():
    model_path = "kha-white/manga-ocr-base"
    print("--- Manga OCR & Batch Translation Tool ---")

    if not os.path.exists(IMAGE_FOLDER):
        print(f"Creating '{IMAGE_FOLDER}' directory. Please put your images there.")
        os.makedirs(IMAGE_FOLDER, exist_ok=True)
        return

    # Find images
    extensions = ["*.webp", "*.jpg", "*.jpeg", "*.png", "*.bmp"]
    image_files = []
    for ext in extensions:
        image_files.extend(glob.glob(os.path.join(IMAGE_FOLDER, ext)))
    
    if not image_files:
        print(f"No images found in '{IMAGE_FOLDER}'. Please add images to that folder.")
        # Fallback for the test image in root if user didn't move it
        if os.path.exists("test_image.webp"):
             print("Found 'test_image.webp' in root, processing that as a demo...")
             image_files.append("test_image.webp")
        else:
             return

    print(f"Loading model '{model_path}' from Hugging Face Hub...")
    try:
        processor = TrOCRProcessor.from_pretrained(model_path)
        model = VisionEncoderDecoderModel.from_pretrained(model_path)
    except Exception as e:
        print(f"Error loading model: {e}")
        return

    print(f"Found {len(image_files)} images to process.")

    for img_path in image_files:
        print(f"\nProcessing: {os.path.basename(img_path)}")
        try:
            image = Image.open(img_path).convert("RGB")
            pixel_values = processor(images=image, return_tensors="pt").pixel_values
            
            generated_ids = model.generate(pixel_values)
            generated_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

            print(f"  [JP]: {generated_text}")
            
            translation = translate_text(generated_text, API_KEY)
            print(f"  [EN]: {translation}")

        except Exception as e:
            print(f"  Error processing {img_path}: {e}")

if __name__ == "__main__":
    main()
