"""
test_unfollow_diagnostic.py
---------------------------
Diagnostic tool to test and inspect Instagram unfollow requests, headers,
cookie validity, and endpoint responses.
"""

import sys
import json
import logging
import ssl
import urllib3
import requests
from pathlib import Path
from dotenv import load_dotenv

ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = BASE_DIR / ".session"
load_dotenv(BASE_DIR / ".env")

import os

TARGET_USERNAME = os.getenv("INSTAGRAM_USERNAME", "darsal1a").strip().lstrip("@")

# Step 3 sends REAL unfollow requests. It only runs with an explicit --send flag
# so running the diagnostic does not silently unfollow anyone.
SEND_UNFOLLOW = "--send" in sys.argv
_args = [a for a in sys.argv[1:] if a != "--send"]
TEST_TARGET_ID = _args[0] if len(_args) > 0 else "1328326366"  # default to @__ekkako__ from logs
TEST_TARGET_USER = _args[1] if len(_args) > 1 else "__ekkako__"

def run_diagnostics():
    print("=" * 65)
    print("  INSTAGRAM UNFOLLOW END-TO-END DIAGNOSTICS")
    print("=" * 65)

    if not SESSION_FILE.exists():
        print(f"[ERROR] Session file not found: {SESSION_FILE}")
        return

    import instaloader
    loader = instaloader.Instaloader(quiet=True)
    try:
        loader.load_session_from_file(TARGET_USERNAME, str(SESSION_FILE))
        cookies = loader.context._session.cookies
    except Exception as exc:
        print(f"[ERROR] Failed to load session from file: {exc}")
        return

    cookie_dict = cookies.get_dict()
    print("\n--- 1. COOKIE AUDIT ---")
    for key in ["sessionid", "csrftoken", "ds_user_id", "mid"]:
        val = cookie_dict.get(key)
        if val:
            preview = val[:12] + "..." if len(val) > 12 else val
            print(f"  [+] {key:<12}: Present ({preview})")
        else:
            print(f"  [-] {key:<12}: MISSING")

    sessionid = cookie_dict.get("sessionid", "")
    csrftoken = cookie_dict.get("csrftoken", "")
    ds_user_id = cookie_dict.get("ds_user_id", "")

    # Configure session
    s = requests.Session()
    s.verify = False
    s.cookies.update(cookies)

    # 2. Check Auth Status
    print("\n--- 2. AUTHENTICATION VALIDITY CHECK ---")
    auth_url = "https://www.instagram.com/api/v1/accounts/current_user/?edit=true"
    auth_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "X-CSRFToken": csrftoken,
        "X-IG-App-ID": "936619743392459",
    }
    try:
        auth_resp = s.get(auth_url, headers=auth_headers, timeout=10, allow_redirects=False)
        print(f"  Endpoint: {auth_url}")
        print(f"  Status  : {auth_resp.status_code}")
        if auth_resp.status_code == 200:
            print(f"  Result  : VALID SESSION (User: {auth_resp.json().get('user', {}).get('username')})")
        elif auth_resp.status_code in (301, 302):
            print(f"  Result  : REDIRECT 302 -> {auth_resp.headers.get('Location')}")
            print(f"  Diagnosis: Session ID is expired or revoked. Login is required.")
        elif auth_resp.status_code == 401:
            print(f"  Result  : 401 UNAUTHORIZED -> {auth_resp.text}")
            print(f"  Diagnosis: Session ID is invalid or rejected by Instagram.")
        else:
            print(f"  Result  : Status {auth_resp.status_code} -> {auth_resp.text[:120]}")
    except Exception as e:
        print(f"  Error checking auth: {e}")

    # 3. Test Unfollow Endpoints
    print("\n--- 3. UNFOLLOW ENDPOINT COMPARISON ---")
    if not SEND_UNFOLLOW:
        print(f"  Skipped: this step really unfollows @{TEST_TARGET_USER} (id {TEST_TARGET_ID}).")
        print("  Re-run with --send to execute it:")
        print(f"    python test_unfollow_diagnostic.py {TEST_TARGET_ID} {TEST_TARGET_USER} --send")
        print("\n" + "=" * 65)
        return
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "X-CSRFToken": csrftoken,
        "X-IG-App-ID": "936619743392459",
        "X-Instagram-AJAX": "1009890256",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/{TEST_TARGET_USER}/",
        "Origin": "https://www.instagram.com",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = {"user_id": str(TEST_TARGET_ID)}

    endpoints = [
        ("Mobile/Web API (api/v1/friendships/destroy)", f"https://www.instagram.com/api/v1/friendships/destroy/{TEST_TARGET_ID}/"),
        ("Legacy Web Endpoint (web/friendships/unfollow)", f"https://www.instagram.com/web/friendships/{TEST_TARGET_ID}/unfollow/"),
    ]

    for label, url in endpoints:
        print(f"\nTesting [{label}]:")
        print(f"  POST -> {url}")
        print(f"  Payload: {payload}")
        try:
            resp = s.post(url, headers=req_headers, data=payload, timeout=12, allow_redirects=False)
            print(f"  Status Code: {resp.status_code}")
            if "Location" in resp.headers:
                print(f"  Redirect Location: {resp.headers['Location']}")
            print(f"  Response Preview: {resp.text[:200] if resp.text else '(Empty body)'}")
            if resp.status_code == 200:
                print("  => SUCCESS: Action succeeded!")
            elif resp.status_code in (301, 302):
                print(f"  => 302 REDIRECT DETECTED: Instagram redirected to {resp.headers.get('Location')}")
        except Exception as e:
            print(f"  Request exception: {e}")

    print("\n" + "=" * 65)

if __name__ == "__main__":
    run_diagnostics()
