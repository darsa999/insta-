"""
instagram_actions.py
--------------------
Authenticated Instagram actions module for @darsal1a.
Handles session loading, numeric user ID resolution, live unfollow requests,
checkpoint/rate-limit detection, and immediate SQLite database synchronization.
"""

import os
import sys
import time
import random
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

# SSL / Insecure warnings workaround (Windows / Python 3.14)
import ssl
import urllib3

ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "instagram_tracker.db"
SESSION_FILE = BASE_DIR / ".session"
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)
TARGET_USERNAME = os.getenv("INSTAGRAM_USERNAME", "darsal1a").strip().lstrip("@")

log = logging.getLogger("instagram_actions")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
IG_APP_ID = "936619743392459"


def get_db() -> sqlite3.Connection:
    """Return an SQLite connection with Row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def get_target_profile_id(conn: sqlite3.Connection) -> int:
    """Return profile_id for target profile (darsal1a)."""
    cur = conn.execute("SELECT id FROM monitored_profiles WHERE username = ?", (TARGET_USERNAME,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO monitored_profiles (username) VALUES (?)", (TARGET_USERNAME,))
    conn.commit()
    return cur.lastrowid


def load_session() -> tuple[requests.Session | None, str | None, str | None]:
    """
    Load .session file and configure an authenticated requests.Session.
    Returns:
      (session, csrftoken, error_message)
    """
    if not SESSION_FILE.exists():
        return None, None, f"Session file not found at {SESSION_FILE}."

    try:
        import instaloader
        loader = instaloader.Instaloader(quiet=True)
        loader.load_session_from_file(TARGET_USERNAME, str(SESSION_FILE))
        cookies = loader.context._session.cookies

        session = requests.Session()
        session.verify = False
        session.cookies.update(cookies)

        csrftoken = cookies.get("csrftoken", "")
        session.headers.update({
            "User-Agent": WEB_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "X-IG-App-ID": IG_APP_ID,
            "X-Instagram-AJAX": "1",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.instagram.com/",
            "Origin": "https://www.instagram.com",
        })
        if csrftoken:
            session.headers["X-CSRFToken"] = csrftoken

        return session, csrftoken, None
    except Exception as exc:
        return None, None, f"Failed to load session: {exc}"


def resolve_user_id(username: str, session: requests.Session | None = None) -> str | None:
    """
    Resolve username to numeric Instagram user_id.
    Checks SQLite cache first, then following/followers tables, then web API.
    """
    username = username.strip().lstrip("@")
    conn = get_db()

    # 1. Check cache
    try:
        cur = conn.execute("SELECT user_id FROM user_id_cache WHERE username = ?", (username,))
        row = cur.fetchone()
        if row and row["user_id"]:
            conn.close()
            return str(row["user_id"])
    except Exception:
        pass

    # 2. Check following / followers tables
    for tbl, col in [("following", "following_username"), ("followers", "follower_username")]:
        try:
            cur = conn.execute(f"SELECT user_id FROM {tbl} WHERE {col} = ? AND user_id IS NOT NULL", (username,))
            row = cur.fetchone()
            if row and row["user_id"]:
                uid = str(row["user_id"])
                conn.execute("INSERT OR REPLACE INTO user_id_cache (username, user_id) VALUES (?, ?)", (username, uid))
                conn.commit()
                conn.close()
                return uid
        except Exception:
            pass

    # 3. Web query fallback if session available
    if session is None:
        session, _, _ = load_session()

    if session:
        # Search via web search API
        try:
            url = f"https://www.instagram.com/api/v1/web/search/topsearch/?context=blended&query={username}"
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("users", []):
                    u = item.get("user", {})
                    if u.get("username", "").lower() == username.lower():
                        uid = str(u.get("pk") or u.get("id"))
                        if uid:
                            conn.execute("INSERT OR REPLACE INTO user_id_cache (username, user_id) VALUES (?, ?)", (username, uid))
                            conn.commit()
                            conn.close()
                            return uid
        except Exception as e:
            log.debug("Topsearch lookup error for '%s': %s", username, e)

        # Web profile info fallback
        try:
            url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                uid = str(resp.json().get("data", {}).get("user", {}).get("id", ""))
                if uid:
                    conn.execute("INSERT OR REPLACE INTO user_id_cache (username, user_id) VALUES (?, ?)", (username, uid))
                    conn.commit()
                    conn.close()
                    return uid
        except Exception as e:
            log.debug("web_profile_info lookup error for '%s': %s", username, e)

    conn.close()
    return None


def remove_following_from_db(username: str) -> bool:
    """
    Remove record from following table in instagram_tracker.db upon successful unfollow,
    and log an event to follower_events.
    """
    username = username.strip().lstrip("@")
    try:
        conn = get_db()
        with conn:
            pid = get_target_profile_id(conn)
            cur = conn.execute(
                "DELETE FROM following WHERE profile_id = ? AND following_username = ?",
                (pid, username)
            )
            deleted = cur.rowcount > 0
            conn.execute(
                "INSERT INTO follower_events (profile_id, event_type, username, detected_at) VALUES (?, 'unfollowed_by_user', ?, ?)",
                (pid, username, datetime.now(timezone.utc).isoformat())
            )
        conn.close()
        log.info("Database: Removed @%s from following table (deleted=%s).", username, deleted)
        return True
    except Exception as exc:
        log.error("Database error removing @%s from following: %s", username, exc)
        return False


def _check_checkpoint_or_rate_limit(status_code: int, response_text: str, data: dict) -> tuple[bool, str]:
    """Helper to detect Instagram rate limiting, checkpoints, or action blocks."""
    if status_code == 429:
        return True, "Rate limit (HTTP 429) triggered by Instagram."

    msg = ""
    if data:
        msg = str(data.get("message") or data.get("feedback_message") or "")
        checkpoint_url = data.get("checkpoint_url")
        if checkpoint_url:
            return True, f"Instagram checkpoint required ({checkpoint_url})."

    text_lower = (response_text or "").lower()
    msg_lower = msg.lower()

    if "checkpoint" in text_lower or "checkpoint" in msg_lower:
        return True, f"Instagram checkpoint required: {msg or 'Checkpoint encountered'}"
    if "feedback_required" in text_lower or "feedback_required" in msg_lower:
        return True, f"Instagram action block (feedback_required): {msg or 'Action blocked'}"
    if "challenge_required" in text_lower or "challenge_required" in msg_lower:
        return True, f"Instagram challenge required: {msg or 'Challenge encountered'}"
    if "please wait a few minutes" in text_lower or "please wait a few minutes" in msg_lower:
        return True, "Rate limit: Instagram requested waiting a few minutes."
    if "action_blocked" in text_lower or "action blocked" in text_lower:
        return True, f"Instagram action blocked: {msg or 'Action blocked'}"
    if "login_required" in text_lower or "login_required" in msg_lower:
        return True, "Session invalid (login_required). Please re-import browser cookies."

    return False, ""


def unfollow_user(
    username: str,
    user_id: str | None = None,
    session: requests.Session | None = None,
    csrftoken: str | None = None,
) -> tuple[bool, str, bool]:
    """
    Send unfollow POST request to Instagram.
    Loads a fresh session directly from .session on each call without reusing stale memory objects.
    
    Returns:
      (success: bool, status_message: str, is_fatal: bool)
    """
    username = username.strip().lstrip("@")

    # 1. Load fresh session directly from .session on each call
    if not SESSION_FILE.exists():
        return False, f"Session file not found at {SESSION_FILE}. Please import browser session cookies.", True

    try:
        import instaloader
        loader = instaloader.Instaloader(quiet=True)
        loader.load_session_from_file(TARGET_USERNAME, str(SESSION_FILE))
        loader_cookies = loader.context._session.cookies
    except Exception as exc:
        return False, f"Failed to load fresh session from {SESSION_FILE}: {exc}", True

    # 2. Explicitly extract csrftoken and ds_user_id from cookies
    csrf_token = loader_cookies.get("csrftoken") or ""
    ds_user_id = loader_cookies.get("ds_user_id") or ""

    if not csrf_token:
        csrf_token = loader_cookies.get_dict().get("csrftoken", "")

    # Create a fresh, isolated requests.Session
    fresh_session = requests.Session()
    fresh_session.verify = False
    fresh_session.cookies.update(loader_cookies)

    # 3. Resolve user_id if not provided
    if not user_id:
        user_id = resolve_user_id(username, session=fresh_session)

    if not user_id:
        return False, f"Could not resolve numeric user ID for @{username}.", False

    # 4. Configure request headers strictly
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-CSRFToken": csrf_token,
        "X-Instagram-AJAX": "1",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/",
        "Origin": "https://www.instagram.com",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # 5. POST endpoint with data={}, allow_redirects=False, and timeout=15
    endpoint = f"https://www.instagram.com/web/friendships/{user_id}/unfollow/"

    try:
        resp = fresh_session.post(
            endpoint,
            headers=headers,
            data={},
            timeout=15,
            allow_redirects=False,
        )
        status_code = resp.status_code

        # If status_code == 200 and json().get("status") == "ok", return (True, "Success", False)
        if status_code == 200:
            data = resp.json() if resp.content else {}
            if data.get("status") == "ok":
                remove_following_from_db(username)
                return True, "Success", False
            else:
                msg = data.get("message") or str(data)
                is_fatal, halt_reason = _check_checkpoint_or_rate_limit(status_code, resp.text, data)
                return False, halt_reason if is_fatal else f"Instagram returned: {msg}", is_fatal

        # If status_code == 302, catch it cleanly and log target location
        if status_code in (301, 302, 303, 307, 308):
            target_location = resp.headers.get("Location", "")
            log.warning("Unfollow HTTP %d redirect for @%s to target location: %s", status_code, username, target_location)
            return False, f"HTTP 302 redirect to {target_location} (Session expired or login required).", True

        # Rate limit (HTTP 429)
        if status_code == 429:
            return False, "Rate limit reached (HTTP 429). Instagram is throttling requests.", True

        # Check for 401 / 403
        if status_code in (401, 403):
            return False, f"Authentication/Session expired (HTTP {status_code}). Please re-import browser session cookies.", True

        # Other checkpoint / action blocks
        is_fatal, halt_reason = _check_checkpoint_or_rate_limit(status_code, resp.text, {})
        if is_fatal:
            return False, halt_reason, True

        return False, f"Instagram error (HTTP {status_code}): {resp.text[:140]}", False

    except requests.exceptions.TooManyRedirects:
        return False, "Authentication/Session expired (Exceeded redirects). Please re-import browser session.", True
    except Exception as exc:
        return False, f"Network error sending unfollow for @{username}: {exc}", False
