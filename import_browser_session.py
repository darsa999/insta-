"""
import_browser_session.py
-------------------------
Extracts Instagram session cookies from your local browser
(Chrome, Edge, Firefox, or Brave) and saves them as an
Instaloader .session file, bypassing the need to log in
via the API entirely.

BEFORE RUNNING
--------------
  Chrome / Edge / Brave:  CLOSE the browser COMPLETELY first.
                           Windows locks the SQLite cookie DB while
                           the browser is open — the script will fail
                           with a "database is locked" error otherwise.

  Firefox:                 Can usually be read while open, but closing
                           it first is safer and more reliable.

USAGE
-----
  python import_browser_session.py [chrome|edge|firefox|brave]

  No argument → tries Chrome → Edge → Firefox → Brave in order.

EXAMPLES
--------
  python import_browser_session.py edge
  python import_browser_session.py firefox
  python import_browser_session.py          # auto-detect
"""

# ---------------------------------------------------------------------------
# SSL fix — before any network-touching import
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Standard imports
# ---------------------------------------------------------------------------
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import instaloader

BASE_DIR     = Path(__file__).resolve().parent
SESSION_FILE = str(BASE_DIR / ".session")
IG_DOMAIN    = "instagram.com"

load_dotenv(BASE_DIR / ".env")
IG_USERNAME = os.getenv("INSTAGRAM_USERNAME", "darsal1a").strip()


# ---------------------------------------------------------------------------
# Cookie extraction via browser-cookie3
# ---------------------------------------------------------------------------

def extract_cookies(browser: str):
    """
    Extract instagram.com cookies from the given browser using browser-cookie3.
    Returns a cookiejar on success, None on failure.
    """
    try:
        import browser_cookie3
    except ImportError:
        print("[ERROR] browser-cookie3 not installed — run: pip install browser-cookie3")
        sys.exit(1)

    extractors = {
        "chrome":   browser_cookie3.chrome,
        "edge":     browser_cookie3.edge,
        "firefox":  browser_cookie3.firefox,
        "brave":    browser_cookie3.brave,
    }

    fn = extractors.get(browser.lower())
    if fn is None:
        print(f"[ERROR] Unknown browser '{browser}'. "
              f"Choose from: {', '.join(extractors)}")
        sys.exit(1)

    print(f"  Extracting cookies from {browser.capitalize()}...")
    try:
        jar = fn(domain_name=IG_DOMAIN)
        return jar
    except PermissionError:
        print(f"  [!] Permission denied — {browser.capitalize()} is likely still open.")
        print(f"      Close it completely (all windows + system tray) and try again.")
        return None
    except Exception as exc:
        err = str(exc)
        if "database is locked" in err.lower():
            print(f"  [!] Cookie database locked — {browser.capitalize()} is still open.")
            print(f"      Close it fully and retry.")
        elif "no such file" in err.lower() or "cannot find" in err.lower():
            print(f"  [!] {browser.capitalize()} cookie file not found.")
            print(f"      Is {browser.capitalize()} installed and have you ever logged "
                  f"into Instagram in it?")
        else:
            print(f"  [!] Failed to read {browser.capitalize()} cookies: {exc}")
        return None


# ---------------------------------------------------------------------------
# Session builder
# ---------------------------------------------------------------------------

def build_session(jar) -> instaloader.Instaloader | None:
    """
    Load *jar* into a fresh Instaloader, verify the session is valid,
    and return the loader. Returns None on failure.
    """
    # Audit the cookie jar
    ig_cookies = [c for c in jar if IG_DOMAIN in c.domain]
    names      = {c.name for c in ig_cookies}
    print(f"  Found {len(ig_cookies)} Instagram cookie(s): {sorted(names)}")

    if "sessionid" not in names:
        print("  [!] 'sessionid' cookie is missing.")
        print("      Make sure you are actually logged into instagram.com "
              "in this browser.")
        return None

    # Show the sessionid value (first 8 chars only for security)
    for c in ig_cookies:
        if c.name == "sessionid":
            preview = c.value[:8] + "..." if len(c.value) > 8 else c.value
            print(f"  sessionid starts with: {preview}")

    # Inject into Instaloader's requests session
    L = instaloader.Instaloader(quiet=True)
    L.context._session.cookies.update(jar)

    # Verify via Instagram's lightweight /api/v1/accounts/current_user/ endpoint
    # (avoids the GraphQL 400 errors that hit Profile.from_username())
    print(f"  Verifying session for @{IG_USERNAME}...")
    try:
        import requests as _r
        test_session = _r.Session()
        test_session.verify = False
        test_session.cookies.update(jar)
        test_session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "X-CSRFToken": next(
                (c.value for c in jar if c.name == "csrftoken"), ""
            ),
        })
        resp = test_session.get(
            "https://www.instagram.com/api/v1/accounts/current_user/?edit=true",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            user = data.get("user", {})
            logged_username = user.get("username", "unknown")
            follower_count  = user.get("follower_count", "?")
            L.context.username = logged_username
            print(f"  [OK] Session valid — logged in as @{logged_username} "
                  f"({follower_count} followers)")
            return L
        elif resp.status_code == 401:
            print("  [!] Session not authenticated (401). "
                  "Make sure you are logged into Instagram in Firefox.")
            return None
        else:
            print(f"  [!] Verification returned HTTP {resp.status_code}. "
                  "Saving session anyway and hoping for the best...")
            L.context.username = IG_USERNAME
            return L   # still save — cookies may work for instaloader even if
                       # this endpoint is quirky
    except Exception as exc:
        print(f"  [!] Verification request failed: {exc}")
        print("  Saving session anyway — cookies were found and look valid.")
        L.context.username = IG_USERNAME
        return L


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

BROWSER_ORDER = ["edge", "chrome", "firefox", "brave"]


def main() -> None:
    requested = sys.argv[1].lower().strip() if len(sys.argv) > 1 else None
    browsers  = [requested] if requested else BROWSER_ORDER

    print(f"\n{'=' * 55}")
    print("  Instagram Browser Session Importer")
    print(f"  Target account : @{IG_USERNAME}")
    print(f"{'=' * 55}\n")

    L = None
    for browser in browsers:
        print(f"[{browser.upper()}]")
        jar = extract_cookies(browser)
        if jar is None:
            print()
            continue

        L = build_session(jar)
        if L is not None:
            break
        print()

    if L is None:
        print("\n[FAIL] Could not create a valid session from any browser.")
        print()
        print("Troubleshooting:")
        print("  1. Make sure the browser is FULLY closed (not just minimised).")
        print("  2. Confirm you are logged into instagram.com in that browser.")
        print("  3. Specify a browser explicitly:")
        print("         python import_browser_session.py firefox")
        print("         python import_browser_session.py edge")
        print("         python import_browser_session.py chrome")
        sys.exit(1)

    # Save session
    L.save_session_to_file(SESSION_FILE)
    print(f"\n[SAVED] Session file written -> {SESSION_FILE}")
    print()
    print("You can now run:")
    print("    python tracker.py darsal1a --analyze")
    print("    python tracker.py darsal1a")


if __name__ == "__main__":
    main()
