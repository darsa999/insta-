"""
save_session.py
---------------
Logs into Instagram using credentials from .env, handles checkpoints
and 2FA interactively, then saves the session to .session.

Usage:
    python save_session.py
"""

# SSL fix
import ssl
import urllib3
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import requests as _req
    _Orig = _req.Session
    class _NoVerify(_Orig):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.verify = False
    _req.Session = _NoVerify  # type: ignore[misc]
except Exception:
    pass

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import instaloader

BASE_DIR     = Path(__file__).resolve().parent
SESSION_FILE = str(BASE_DIR / ".session")

load_dotenv(BASE_DIR / ".env")
username = os.getenv("INSTAGRAM_USERNAME", "").strip()
password = os.getenv("INSTAGRAM_PASSWORD", "").strip()

if not username or not password:
    print("[ERROR] INSTAGRAM_USERNAME or INSTAGRAM_PASSWORD missing from .env")
    sys.exit(1)

print(f"\nLogging into Instagram as '{username}'...")

L = instaloader.Instaloader(quiet=True)

try:
    L.login(username, password)
    L.save_session_to_file(SESSION_FILE)
    print(f"\n[OK] Login successful! Session saved.")
    print("You can now run:  python tracker.py darsal1a --analyze")
    sys.exit(0)

except instaloader.exceptions.TwoFactorAuthRequiredException:
    print("\n[2FA] Instagram requires a two-factor authentication code.")
    code = input("Enter the 6-digit code from your authenticator / SMS: ").strip()
    try:
        L.two_factor_login(code)
        L.save_session_to_file(SESSION_FILE)
        print(f"\n[OK] 2FA login successful! Session saved.")
        print("You can now run:  python tracker.py darsal1a --analyze")
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] 2FA failed: {e}")
        sys.exit(1)

except instaloader.exceptions.LoginException as exc:
    err = str(exc)
    # ----------------------------------------------------------------
    # Checkpoint — Instagram wants an emailed / SMS code.
    # Try to handle it by asking the user for the code right here.
    # ----------------------------------------------------------------
    if "Checkpoint" in err or "checkpoint" in err:
        print("\n[CHECKPOINT] Instagram sent a verification code to your")
        print("             email or phone number linked to 'darsal1a'.")
        print()
        code = input("Enter the verification code Instagram sent you: ").strip()

        # Instaloader exposes the raw requests session via L.context._session
        # We POST the code to the checkpoint URL to complete verification.
        try:
            ctx = L.context
            # Extract checkpoint URL from the error message
            import re
            match = re.search(r"/auth_platform/[^\s]+", err)
            if match:
                checkpoint_url = "https://www.instagram.com" + match.group(0)
            else:
                checkpoint_url = "https://www.instagram.com/challenge/"

            # Submit the security code
            session = ctx._session
            response = session.post(
                "https://www.instagram.com/challenge/",
                data={"security_code": code},
                headers={"Referer": checkpoint_url},
                allow_redirects=True,
            )

            if response.status_code == 200 and "checkpoint" not in response.url:
                # Now try logging in again
                L2 = instaloader.Instaloader(quiet=True)
                L2.login(username, password)
                L2.save_session_to_file(SESSION_FILE)
                print(f"\n[OK] Checkpoint cleared! Session saved.")
                print("You can now run:  python tracker.py darsal1a --analyze")
                sys.exit(0)
            else:
                print("[WARN] Checkpoint POST returned unexpected response.")
                print("       Please complete verification at instagram.com/challenge/")
                sys.exit(1)

        except Exception as e2:
            print(f"[ERROR] Could not submit checkpoint code: {e2}")
            print("\nFallback: please verify at instagram.com in your browser,")
            print("then run this script again.")
            sys.exit(1)
    else:
        print(f"\n[ERROR] Login failed: {exc}")
        sys.exit(1)

except Exception as e:
    print(f"\n[ERROR] Unexpected error: {e}")
    sys.exit(1)
