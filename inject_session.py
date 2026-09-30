"""
inject_session.py
-----------------
Directly injects and saves an authenticated Instagram session to `.session`
for user @darsal1a without requiring browser cookie extraction.
"""

import os
import sys
import ssl
import urllib3
import requests
from pathlib import Path
import instaloader

# Bypass SSL verification issues on Python 3.14/Windows
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = str(BASE_DIR / ".session")
load_dotenv(BASE_DIR / ".env")

SESSION_ID = sys.argv[1] if len(sys.argv) > 1 else os.getenv("INSTAGRAM_SESSION_ID", "YOUR_SESSION_ID_HERE")
USER_ID = os.getenv("INSTAGRAM_USER_ID", "46754714624")
USERNAME = os.getenv("INSTAGRAM_USERNAME", "darsal1a").strip().lstrip("@")

def inject_and_save():
    print(f"\n{'='*55}")
    print(f"  Injecting Instagram Session for @{USERNAME}")
    print(f"{'='*55}\n")

    L = instaloader.Instaloader(quiet=True)
    session = L.context._session

    # Fetch initial cookies (csrftoken, mid, ig_did) from Instagram
    print("[*] Fetching lightweight CSRF and base cookies from instagram.com...")
    try:
        resp = session.get(
            "https://www.instagram.com/",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=10,
            verify=False,
        )
        csrf = session.cookies.get("csrftoken", domain=".instagram.com") or resp.cookies.get("csrftoken", "")
    except Exception as e:
        print(f"[!] Warning: Could not fetch initial cookies from Instagram: {e}")
        csrf = ""

    if not csrf:
        # Fallback to random 32-character hex token if network fetch didn't return one
        import secrets
        csrf = secrets.token_hex(16)
        print(f"[*] Generated fallback CSRF token.")

    print(f"[*] CSRF Token: {csrf[:8]}...")

    # Set required authentication cookies for .instagram.com
    cookie_kwargs = {"domain": ".instagram.com", "path": "/"}
    session.cookies.set("sessionid", SESSION_ID, **cookie_kwargs)
    session.cookies.set("ds_user_id", USER_ID, **cookie_kwargs)
    session.cookies.set("csrftoken", csrf, **cookie_kwargs)

    # Set user context
    L.context.username = USERNAME

    # Save to .session file
    print(f"[*] Saving session file to: {SESSION_FILE}")
    L.save_session_to_file(SESSION_FILE)

    print(f"\n[SUCCESS] Successfully saved authenticated session for @{USERNAME}!")
    print(f"Session file created at: {SESSION_FILE}")
    print(f"User ID: {USER_ID}")
    print("="*55 + "\n")

if __name__ == "__main__":
    inject_and_save()
