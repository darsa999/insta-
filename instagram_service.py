"""
instagram_service.py
--------------------
Core automation and database service for Instagram user @darsal1a.
Handles database schema/queries and relationship data. Network actions
(session loading, user ID resolution, unfollow) live in instagram_actions.py;
the wrappers here delegate to it so older callers keep working.
"""

from __future__ import annotations

import os
import time
import random
import sqlite3
import logging
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# SSL Setup (Windows / Python 3.14 workaround)
# WARNING: this disables TLS certificate verification for the whole process.
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
# Single-account target (defaults to @darsal1a)
TARGET_USERNAME = os.getenv("INSTAGRAM_USERNAME", "darsal1a").strip().lstrip("@")

# How many recent events load_relationship_data() returns (the UI shows 60).
EVENTS_LIMIT = 200

log = logging.getLogger("instagram_service")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

_db_initialized = False


# ---------------------------------------------------------------------------
# Database Management & Schema Initialisation
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    """Return a configured SQLite connection with foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS monitored_profiles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT    NOT NULL UNIQUE,
    last_checked TEXT
);

CREATE TABLE IF NOT EXISTS followers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id        INTEGER NOT NULL,
    follower_username TEXT    NOT NULL,
    user_id           TEXT,
    profile_pic_path  TEXT,
    FOREIGN KEY (profile_id) REFERENCES monitored_profiles(id) ON DELETE CASCADE,
    UNIQUE(profile_id, follower_username)
);

CREATE TABLE IF NOT EXISTS following (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id         INTEGER NOT NULL,
    following_username TEXT    NOT NULL,
    user_id            TEXT,
    profile_pic_path   TEXT,
    FOREIGN KEY (profile_id) REFERENCES monitored_profiles(id) ON DELETE CASCADE,
    UNIQUE(profile_id, following_username)
);

CREATE TABLE IF NOT EXISTS follower_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL,
    event_type  TEXT    NOT NULL,  -- 'new_follower' | 'unfollower' | 'unfollowed_by_user'
    username    TEXT    NOT NULL,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (profile_id) REFERENCES monitored_profiles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_profile_time
    ON follower_events(profile_id, detected_at);

CREATE TABLE IF NOT EXISTS user_id_cache (
    username   TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables/indexes and apply column migrations on an open connection."""
    conn.executescript(SCHEMA)
    for tbl in ("followers", "following"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")}
        if "user_id" not in cols:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN user_id TEXT")


def init_database(force: bool = False) -> None:
    """Ensure the schema exists and the target profile row is present.

    Runs once per process (Streamlit reruns the script on every click, so
    repeating the DDL each time was wasted work). Pass force=True to re-run.
    """
    global _db_initialized
    if _db_initialized and not force and DB_PATH.exists():
        return

    conn = get_db()
    try:
        with conn:
            ensure_schema(conn)
            # Previously hard-coded to 'darsal1a', which created a second
            # profile row whenever INSTAGRAM_USERNAME was set to another account.
            cur = conn.execute(
                "INSERT OR IGNORE INTO monitored_profiles (username) VALUES (?)",
                (TARGET_USERNAME,),
            )
            if cur.rowcount:
                log.info("Initialized root profile row for '%s'.", TARGET_USERNAME)
    finally:
        conn.close()
    _db_initialized = True


def get_target_profile_id(conn: sqlite3.Connection) -> int:
    """Return profile_id for the target account, creating the row if needed."""
    row = conn.execute(
        "SELECT id FROM monitored_profiles WHERE username = ?", (TARGET_USERNAME,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO monitored_profiles (username) VALUES (?)", (TARGET_USERNAME,))
    conn.commit()
    return cur.lastrowid


def load_relationship_data(events_limit: int = EVENTS_LIMIT) -> dict:
    """
    Fetch relationship data for the target account.
    Returns:
      followers: set[str]
      following: set[str]
      mutuals: set[str]
      not_following_back: set[str] (accounts the target follows who don't follow back)
      fans: set[str] (accounts following the target whom it doesn't follow)
      events: list[dict] (most recent `events_limit` events)
      event_count: int (total number of events)
      last_checked: str | None
      user_id_map: dict[str, str]
    """
    init_database()
    conn = get_db()
    try:
        pid = get_target_profile_id(conn)

        row = conn.execute("SELECT last_checked FROM monitored_profiles WHERE id = ?", (pid,)).fetchone()
        last_checked = row["last_checked"] if row else None

        # user_id_cache first so per-profile table IDs take precedence below.
        user_id_map: dict[str, str] = {
            r["username"]: r["user_id"]
            for r in conn.execute("SELECT username, user_id FROM user_id_cache")
            if r["user_id"] and r["user_id"] != "None"
        }

        followers: set[str] = set()
        for r in conn.execute("SELECT follower_username, user_id FROM followers WHERE profile_id = ?", (pid,)):
            followers.add(r["follower_username"])
            if r["user_id"]:
                user_id_map[r["follower_username"]] = r["user_id"]

        following: set[str] = set()
        for r in conn.execute("SELECT following_username, user_id FROM following WHERE profile_id = ?", (pid,)):
            following.add(r["following_username"])
            if r["user_id"]:
                user_id_map[r["following_username"]] = r["user_id"]

        event_count = conn.execute(
            "SELECT COUNT(*) FROM follower_events WHERE profile_id = ?", (pid,)
        ).fetchone()[0]
        events = [
            dict(r)
            for r in conn.execute(
                "SELECT event_type, username, detected_at FROM follower_events "
                "WHERE profile_id = ? ORDER BY detected_at DESC LIMIT ?",
                (pid, events_limit),
            )
        ]
    finally:
        conn.close()

    return {
        "target": TARGET_USERNAME,
        "last_checked": last_checked,
        "followers": followers,
        "following": following,
        "mutuals": followers & following,
        "not_following_back": following - followers,
        "fans": followers - following,
        "events": events,
        "event_count": event_count,
        "user_id_map": user_id_map,
    }


# ---------------------------------------------------------------------------
# Session & Web Request Helpers (implemented once, in instagram_actions)
# ---------------------------------------------------------------------------
def load_session() -> tuple[requests.Session | None, str | None, str | None]:
    """Load .session into an authenticated requests.Session. See instagram_actions.load_session."""
    import instagram_actions
    return instagram_actions.load_session()


def resolve_user_id(username: str, session: requests.Session | None = None) -> str | None:
    """Resolve username to numeric Instagram user_id. See instagram_actions.resolve_user_id."""
    import instagram_actions
    return instagram_actions.resolve_user_id(username, session=session)


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
    Execute a live unfollow. Delegates to instagram_actions.unfollow_user.
    Returns (success: bool, status_message: str).
    """
    import instagram_actions
    success, message, _ = instagram_actions.unfollow_user(
        username=username, user_id=user_id, session=session, csrftoken=csrftoken,
    )
    return success, message


def execute_batch_unfollow(
    usernames: list[str],
    user_id_map: dict[str, str] | None = None,
    min_jitter: float = 3.0,
    max_jitter: float = 6.0,
    progress_callback=None,
    abort_check=None,
) -> dict:
    """
    Executes batch unfollow with jitter delays between every request.
    Stops immediately on a fatal error (rate limit, checkpoint, expired session).
    Calls progress_callback(index, total, username, success, message, delay).
    """
    import instagram_actions

    session, csrftoken, err = load_session()
    if not session:
        return {"success": False, "error": err, "completed": 0, "failed": len(usernames)}

    user_id_map = user_id_map or {}
    results = []
    total = len(usernames)
    halted_reason = None

    for i, username in enumerate(usernames):
        if abort_check and abort_check():
            log.info("Batch unfollow aborted by user.")
            break

        success, msg, is_fatal = instagram_actions.unfollow_user(
            username, user_id=user_id_map.get(username), session=session, csrftoken=csrftoken,
        )

        # Delay after failures too — retrying instantly is what triggers rate limits.
        delay = 0.0
        if i < total - 1 and not is_fatal:
            delay = round(random.uniform(min_jitter, max_jitter), 2)

        results.append({"username": username, "success": success, "message": msg, "delay": delay})

        if progress_callback:
            progress_callback(i + 1, total, username, success, msg, delay)

        if is_fatal:
            halted_reason = msg
            log.warning("Batch unfollow halted: %s", msg)
            break

        if delay > 0:
            time.sleep(delay)

    completed = sum(1 for r in results if r["success"])
    return {
        "success": True,
        "completed": completed,
        "failed": len(results) - completed,
        "halted": halted_reason,
        "details": results,
    }
