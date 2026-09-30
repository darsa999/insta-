"""
instagram_service.py
--------------------
Core automation and database service for Instagram user @darsal1a.
Handles authenticated session management, user ID resolution,
stealth-delayed unfollowing, relationship queries, and database sync.
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

# ---------------------------------------------------------------------------
# SSL Setup (Windows / Python 3.14 workaround)
# ---------------------------------------------------------------------------
import ssl
import urllib3

ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "instagram_tracker.db"
SESSION_FILE = BASE_DIR / ".session"
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)
# Single-account target: strictly @darsal1a
TARGET_USERNAME = os.getenv("INSTAGRAM_USERNAME", "darsal1a").strip().lstrip("@")

log = logging.getLogger("instagram_service")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

_WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Database Management & Schema Initialisation
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    """Return a configured SQLite connection with foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    """Ensure database schema supports @darsal1a single-account operations."""
    conn = get_db()
    with conn:
        # 1. Monitored profiles
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monitored_profiles (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT    NOT NULL UNIQUE,
                last_checked TEXT
            );
        """)

        # 2. Followers table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS followers (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id        INTEGER NOT NULL,
                follower_username TEXT    NOT NULL,
                user_id           TEXT,
                profile_pic_path  TEXT,
                FOREIGN KEY (profile_id) REFERENCES monitored_profiles(id) ON DELETE CASCADE,
                UNIQUE(profile_id, follower_username)
            );
        """)

        # 3. Following table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS following (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id         INTEGER NOT NULL,
                following_username TEXT    NOT NULL,
                user_id            TEXT,
                profile_pic_path   TEXT,
                FOREIGN KEY (profile_id) REFERENCES monitored_profiles(id) ON DELETE CASCADE,
                UNIQUE(profile_id, following_username)
            );
        """)

        # 4. Follower events table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS follower_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id  INTEGER NOT NULL,
                event_type  TEXT    NOT NULL,
                username    TEXT    NOT NULL,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (profile_id) REFERENCES monitored_profiles(id) ON DELETE CASCADE
            );
        """)

        # 5. User ID cache (mapping username -> numeric IG user_id)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_id_cache (
                username   TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Check for column migrations if tables already existed
        for tbl, col in [("followers", "user_id"), ("following", "user_id")]:
            cur = conn.execute(f"PRAGMA table_info({tbl})")
            cols = [r["name"] for r in cur.fetchall()]
            if col not in cols:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT")

        # Ensure root profile row exists strictly for 'darsal1a'
        cur = conn.execute("SELECT id FROM monitored_profiles WHERE username = 'darsal1a'")
        darsal_row = cur.fetchone()
        if not darsal_row:
            conn.execute("INSERT INTO monitored_profiles (username) VALUES ('darsal1a')")
            log.info("Initialized root profile row for 'darsal1a'.")
    conn.close()


def get_target_profile_id(conn: sqlite3.Connection) -> int:
    """Return profile_id for @darsal1a."""
    cur = conn.execute("SELECT id FROM monitored_profiles WHERE username = ?", (TARGET_USERNAME,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO monitored_profiles (username) VALUES (?)", (TARGET_USERNAME,))
    conn.commit()
    return cur.lastrowid


def load_relationship_data() -> dict:
    """
    Fetch relationship data exclusively for @darsal1a.
    Returns:
      followers: set[str]
      following: set[str]
      mutuals: set[str]
      not_following_back: set[str] (accounts darsal1a follows who don't follow back)
      fans: set[str] (accounts following darsal1a whom darsal1a doesn't follow)
      events: list[dict]
      last_checked: str | None
      user_id_map: dict[str, str]
    """
    init_database()
    conn = get_db()
    pid = get_target_profile_id(conn)

    # Get last_checked
    cur = conn.execute("SELECT last_checked FROM monitored_profiles WHERE id = ?", (pid,))
    row = cur.fetchone()
    last_checked = row["last_checked"] if row else None

    # Get followers
    cur = conn.execute("SELECT follower_username, user_id FROM followers WHERE profile_id = ?", (pid,))
    follower_rows = cur.fetchall()
    followers = {r["follower_username"] for r in follower_rows}

    # Get following
    cur = conn.execute("SELECT following_username, user_id FROM following WHERE profile_id = ?", (pid,))
    following_rows = cur.fetchall()
    following = {r["following_username"] for r in following_rows}

    # Build user_id_map
    user_id_map = {}
    for r in follower_rows:
        if r["user_id"]:
            user_id_map[r["follower_username"]] = r["user_id"]
    for r in following_rows:
        if r["user_id"]:
            user_id_map[r["following_username"]] = r["user_id"]

    # Also load from user_id_cache
    cur = conn.execute("SELECT username, user_id FROM user_id_cache")
    for r in cur.fetchall():
        user_id_map[r["username"]] = r["user_id"]

    # Get follower events
    cur = conn.execute(
        "SELECT event_type, username, detected_at FROM follower_events WHERE profile_id = ? ORDER BY detected_at DESC",
        (pid,)
    )
    events = [dict(r) for r in cur.fetchall()]
    conn.close()

    mutuals = followers & following
    not_following_back = following - followers
    fans = followers - following

    return {
        "target": TARGET_USERNAME,
        "last_checked": last_checked,
        "followers": followers,
        "following": following,
        "mutuals": mutuals,
        "not_following_back": not_following_back,
        "fans": fans,
        "events": events,
        "user_id_map": user_id_map,
    }


# ---------------------------------------------------------------------------
# Session & Web Request Helpers
# ---------------------------------------------------------------------------
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
            "User-Agent": _WEB_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "X-IG-App-ID": "936619743392459",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.instagram.com/",
        })
        if csrftoken:
            session.headers["X-CSRFToken"] = csrftoken

        return session, csrftoken, None
    except Exception as exc:
        return None, None, f"Failed to load session: {exc}"


def resolve_user_id(username: str, session: requests.Session | None = None) -> str | None:
    """
    Resolve username to numeric Instagram user_id.
    Checks SQLite cache first, then attempts Web endpoints.
    """
    username = username.strip().lstrip("@")
    
    # Fast path for root target user: extract from session cookies directly
    if username.lower() == TARGET_USERNAME.lower():
        if session:
            c_uid = session.cookies.get("ds_user_id")
            if c_uid:
                return str(c_uid)
        try:
            import instaloader
            L = instaloader.Instaloader(quiet=True)
            L.load_session_from_file(TARGET_USERNAME, str(SESSION_FILE))
            c_uid = L.context._session.cookies.get("ds_user_id")
            if c_uid:
                return str(c_uid)
        except Exception:
            pass

    conn = get_db()
    
    # 1. Check cache
    cur = conn.execute("SELECT user_id FROM user_id_cache WHERE username = ?", (username,))
    row = cur.fetchone()
    if row and row["user_id"]:
        conn.close()
        return row["user_id"]

    # 2. Check following / followers tables
    for tbl, col in [("following", "following_username"), ("followers", "follower_username")]:
        cur = conn.execute(f"SELECT user_id FROM {tbl} WHERE {col} = ? AND user_id IS NOT NULL", (username,))
        row = cur.fetchone()
        if row and row["user_id"]:
            uid = row["user_id"]
            conn.execute("INSERT OR REPLACE INTO user_id_cache (username, user_id) VALUES (?, ?)", (username, uid))
            conn.commit()
            conn.close()
            return uid

    # 3. Web query using session
    if session is None:
        session, _, _ = load_session()

    if session:
        # Try topsearch endpoint
        try:
            url = f"https://www.instagram.com/api/v1/web/search/topsearch/?context=blended&query={username}"
            resp = session.get(url, timeout=12)
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

        # Try web_profile_info
        try:
            url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            resp = session.get(url, timeout=12)
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


# ---------------------------------------------------------------------------
# Unfollow Execution & Database Sync
# ---------------------------------------------------------------------------
def unfollow_user(
    username: str,
    user_id: str | None = None,
    session: requests.Session | None = None,
    csrftoken: str | None = None,
) -> tuple[bool, str]:
    """
    Execute live Unfollow on Instagram using /web/friendships/{user_id}/unfollow/.
    Delegates to instagram_actions for unified action handling and rate-limit safety.
    Returns (success: bool, status_message: str).
    """
    import instagram_actions
    success, message, _ = instagram_actions.unfollow_user(
        username=username,
        user_id=user_id,
        session=session,
        csrftoken=csrftoken,
    )
    return success, message


def _record_unfollow_in_db(username: str) -> None:
    """Immediately remove user from following table and record event."""
    import instagram_actions
    instagram_actions.remove_following_from_db(username)


def execute_batch_unfollow(
    usernames: list[str],
    user_id_map: dict[str, str] | None = None,
    min_jitter: float = 3.0,
    max_jitter: float = 6.0,
    progress_callback=None,
    abort_check=None,
) -> dict:
    """
    Executes batch unfollow with stealth jitter delays (3.0s - 6.0s).
    Calls progress_callback(index, total, username, success, message, delay).
    """
    session, csrftoken, err = load_session()
    if not session:
        return {"success": False, "error": err, "completed": 0, "failed": len(usernames)}

    results = []
    total = len(usernames)

    for i, username in enumerate(usernames):
        if abort_check and abort_check():
            log.info("Batch unfollow aborted by user.")
            break

        uid = (user_id_map or {}).get(username)
        success, msg = unfollow_user(username, user_id=uid, session=session, csrftoken=csrftoken)
        
        delay = 0.0
        # If not the last user, apply human-mimicking jitter delay
        if i < total - 1 and success:
            delay = round(random.uniform(min_jitter, max_jitter), 2)

        results.append({
            "username": username,
            "success": success,
            "message": msg,
            "delay": delay,
        })

        if progress_callback:
            progress_callback(i + 1, total, username, success, msg, delay)

        if delay > 0:
            time.sleep(delay)

    completed = sum(1 for r in results if r["success"])
    failed = len(results) - completed
    return {
        "success": True,
        "completed": completed,
        "failed": failed,
        "details": results,
    }
