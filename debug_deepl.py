import requests
import json
import os

CONFIG_FILE = "user_config.json"

def test_connection():
    print("--- DeepL API Debug Tool ---")
    
    api_key = ""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                api_key = config.get("api_key", "").strip()
                print(f"Found API Key in config: {api_key[:4]}...{api_key[-4:]} (Length: {len(api_key)})")
        except Exception as e:
            print(f"Error reading config: {e}")
    else:
        print("No user_config.json found.")
    
    if not api_key:
        print("No API Key found to test.")
        return

    # Check for hidden characters
    if not api_key.isprintable():
        print("WARNING: API Key contains non-printable characters! Please re-enter it carefully.")
    
    # Test Free Endpoint
    url_free = "https://api-free.deepl.com/v2/translate"
    print(f"\nTesting FREE Endpoint ({url_free})...")
    try:
        headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}
        r = requests.post(url_free, headers=headers, data={"text": "Hello", "target_lang": "DE"})
        print(f"Status Code: {r.status_code}")
        print(f"Response: {r.text}")
    except Exception as e:
        print(f"Request failed: {e}")

    # Test Pro Endpoint
    url_pro = "https://api.deepl.com/v2/translate"
    print(f"\nTesting PRO Endpoint ({url_pro})...")
    try:
        headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}
        r = requests.post(url_pro, headers=headers, data={"text": "Hello", "target_lang": "DE"})
        print(f"Status Code: {r.status_code}")
        print(f"Response: {r.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_connection()
