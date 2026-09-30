"""
sync_accurate_data.py
---------------------
Fetches the accurate followers and following lists for @darsal1a
using the saved browser session, then writes everything to the
SQLite database with user IDs and records historical follower diff events.

Usage:
    python sync_accurate_data.py
    python sync_accurate_data.py darsal1a
"""

# ---------------------------------------------------------------------------
# SSL fix — before any network import
# ---------------------------------------------------------------------------
import ssl, urllib3
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    import requests as _req
    _Orig = _req.Session
    class _NV(_Orig):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.verify = False
    _req.Session = _NV  # type: ignore
except Exception:
    pass

import os, sys, time, sqlite3, logging, random, subprocess
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
import instaloader
import requests

BASE_DIR     = Path(__file__).resolve().parent
DB_PATH      = BASE_DIR / "instagram_tracker.db"
SESSION_FILE = str(BASE_DIR / ".session")

load_dotenv(BASE_DIR / ".env")
IG_USER = os.getenv("INSTAGRAM_USERNAME", "darsal1a").strip().lstrip("@")
TARGET  = sys.argv[1].strip().lstrip("@") if len(sys.argv) > 1 else IG_USER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Desktop browser headers & Web API settings
# ---------------------------------------------------------------------------
_WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
}

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def refresh_session_cache():
    """Tries to rebuild .session from browser cookies to get a fresh connection state."""
    print("\n[*] Checking browser session cache...")
    try:
        import_script = BASE_DIR / "import_browser_session.py"
        res = subprocess.run(
            [sys.executable, str(import_script)],
            capture_output=True,
            text=True,
            timeout=30
        )
        if res.returncode == 0:
            print("[+] Session cache successfully refreshed from browser cookies.")
            log.info("Session cache successfully refreshed from browser.")
        else:
            print("[!] Notice: Could not extract fresh cookies from browser (browser may be currently open).")
            print("    -> Proceeding with existing .session cache.")
            log.warning("Browser extraction skipped: browser locked or closed.")
    except Exception as e:
        print(f"[!] Warning: Cookie importer subprocess notice: {e}. Using existing .session.")


def get_loader() -> instaloader.Instaloader:
    if not os.path.exists(SESSION_FILE):
        print("\n" + "="*60)
        print("[ERROR] .session file is missing!")
        print("Please close your browser (Chrome/Edge/Firefox) completely and run:")
        print("    python import_browser_session.py")
        print("="*60 + "\n")
        sys.exit(1)

    L = instaloader.Instaloader(quiet=True)
    try:
        L.load_session_from_file(IG_USER, SESSION_FILE)
        log.info("Session loaded from '%s' for user '%s'.", SESSION_FILE, IG_USER)
    except Exception as exc:
        print("\n" + "="*60)
        print(f"[ERROR] Could not load session from {SESSION_FILE}: {exc}")
        print("Please close your browser completely and run:")
        print("    python import_browser_session.py")
        print("="*60 + "\n")
        sys.exit(1)
    return L


def create_web_session(loader: instaloader.Instaloader) -> requests.Session:
    s = requests.Session()
    s.verify = False
    s.cookies.update(loader.context._session.cookies)
    s.headers.update(_WEB_HEADERS)
    csrf = loader.context._session.cookies.get("csrftoken", "")
    if csrf:
        s.headers["X-CSRFToken"] = csrf
    return s


def resolve_target_user_id(loader: instaloader.Instaloader, sess: requests.Session, username: str) -> str:
    """
    Extracts the user ID directly from session cookies or authenticated endpoint.
    Avoids Instaloader's Profile.from_username which fails with web cookies.
    """
    # 1. Direct extraction from session cookies
    cookie_uid = loader.context._session.cookies.get("ds_user_id") or sess.cookies.get("ds_user_id")
    if cookie_uid:
        log.info("Resolved user ID for @%s directly from 'ds_user_id' cookie: %s", username, cookie_uid)
        return str(cookie_uid)

    # 2. Check context user_id
    ctx_uid = getattr(loader.context, "user_id", None)
    if ctx_uid:
        log.info("Resolved user ID from loader context: %s", ctx_uid)
        return str(ctx_uid)

    # 3. Call lightweight authenticated current_user endpoint
    try:
        log.info("Calling /api/v1/accounts/current_user/?edit=true...")
        resp = sess.get("https://www.instagram.com/api/v1/accounts/current_user/?edit=true", timeout=15)
        if resp.status_code == 200:
            user_data = resp.json().get("user", {})
            pk = user_data.get("pk") or user_data.get("id")
            if pk:
                log.info("Resolved user ID from current_user endpoint: %s", pk)
                return str(pk)
        elif resp.status_code == 401:
            log.warning("current_user endpoint returned 401 Unauthorized.")
    except Exception as e:
        log.warning("current_user query failed: %s", e)

    # 4. Check SQLite user_id_cache
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM user_id_cache WHERE username = ?", (username,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            log.info("Resolved user ID from local SQLite cache: %s", row[0])
            return str(row[0])
    except Exception:
        pass

    raise RuntimeError(
        f"Unable to resolve numeric user ID for @{username}. "
        "Ensure your .session contains valid cookies with 'ds_user_id'."
    )


# ---------------------------------------------------------------------------
# Stealth Web REST API Fetcher
# ---------------------------------------------------------------------------

def fetch_list_stealth(sess: requests.Session, user_id: str, mode: str) -> dict[str, str]:
    """
    Stealthily pages through followers or following with human-mimicking delay logic.
    Returns a dict mapping username -> numeric user_id (pk).
    """
    endpoint = (
        f"https://www.instagram.com/api/v1/friendships/{user_id}/followers/"
        if mode == "followers"
        else f"https://www.instagram.com/api/v1/friendships/{user_id}/following/"
    )
    result = {}
    next_id = None
    page = 1
    accounts_since_pause = 0

    while True:
        params = {"count": 200}
        if next_id:
            params["max_id"] = next_id
        
        log.info("Stealth Fetch: Reading page %d of %s...", page, mode)
        try:
            r = sess.get(endpoint, params=params, timeout=20)
        except Exception as exc:
            log.error("Request error on page %d (%s): %s", page, mode, exc)
            break

        if r.status_code == 401:
            print("\n" + "!"*60)
            print("[ERROR] Instagram returned HTTP 401 Unauthorized.")
            print("Your session cookies have expired. Please:")
            print("1. Close your browser (Chrome/Edge/Firefox) completely.")
            print("2. Run: python import_browser_session.py")
            print("!"*60 + "\n")
            sys.exit(1)

        if r.status_code != 200:
            log.warning("HTTP %d on page %d (%s) — stopping. Response: %s", r.status_code, page, mode, r.text[:200])
            break

        data = r.json()
        users = data.get("users", [])
        
        for u in users:
            uname = u.get("username")
            uid = str(u.get("pk") or u.get("id") or "")
            if uname:
                result[uname] = uid
            accounts_since_pause += 1
            
            # Mimic human pausing to read every 30 accounts
            if accounts_since_pause >= 30:
                delay = random.uniform(2.0, 4.5)
                log.info("  [Stealth Pause] Read 30 accounts. Simulating reading behavior (sleeping %.2fs)...", delay)
                time.sleep(delay)
                accounts_since_pause = 0

        log.info("Page %d yielded %d users. Cumulative unique count: %d", page, len(users), len(result))

        next_id = data.get("next_max_id")
        if not next_id:
            log.info("No next_max_id returned. Finished paginating %s.", mode)
            break
            
        page += 1
        page_delay = random.uniform(1.5, 3.5)
        log.info("Page delay: sleeping for %.2fs before loading next page...", page_delay)
        time.sleep(page_delay)

    log.info("Finished %s list. Total retrieved: %d", mode, len(result))
    return result

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

SCHEMA_MIGRATION = """
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

CREATE TABLE IF NOT EXISTS user_id_cache (
    username   TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def sync_to_db(
    target: str,
    followers: dict[str, str],
    following: dict[str, str],
) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_MIGRATION)

    # Ensure user_id column exists
    for tbl in ["followers", "following"]:
        cur = conn.execute(f"PRAGMA table_info({tbl})")
        cols = [r["name"] for r in cur.fetchall()]
        if "user_id" not in cols:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN user_id TEXT")

    cur = conn.cursor()

    # Get or create monitored profile strictly for target
    cur.execute("SELECT id FROM monitored_profiles WHERE username=?", (target,))
    row = cur.fetchone()
    if row:
        profile_id = row["id"]
    else:
        cur.execute(
            "INSERT INTO monitored_profiles (username, last_checked) VALUES (?, NULL)",
            (target,),
        )
        profile_id = cur.lastrowid
        log.info("Created monitored_profiles entry for '@%s' (id=%d).", target, profile_id)

    # Diff calculation for history events
    old_followers_rows = conn.execute("SELECT follower_username FROM followers WHERE profile_id=?", (profile_id,)).fetchall()
    old_followers = {r[0] for r in old_followers_rows}

    if old_followers:
        current_follower_set = set(followers.keys())
        new_followers = current_follower_set - old_followers
        lost_followers = old_followers - current_follower_set
        now_ts = datetime.now(timezone.utc).isoformat()
        for u in sorted(new_followers):
            conn.execute(
                "INSERT INTO follower_events (profile_id, event_type, username, detected_at) VALUES (?, 'new_follower', ?, ?)",
                (profile_id, u, now_ts)
            )
        for u in sorted(lost_followers):
            conn.execute(
                "INSERT INTO follower_events (profile_id, event_type, username, detected_at) VALUES (?, 'unfollower', ?, ?)",
                (profile_id, u, now_ts)
            )

    # Update followers table
    conn.execute("DELETE FROM followers WHERE profile_id=?", (profile_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO followers (profile_id, follower_username, user_id) VALUES (?,?,?)",
        [(profile_id, u, uid) for u, uid in followers.items()],
    )

    # Update following table
    conn.execute("DELETE FROM following WHERE profile_id=?", (profile_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO following (profile_id, following_username, user_id) VALUES (?,?,?)",
        [(profile_id, u, uid) for u, uid in following.items()],
    )

    # Cache user IDs
    for u, uid in {**followers, **following}.items():
        if uid:
            conn.execute("INSERT OR REPLACE INTO user_id_cache (username, user_id) VALUES (?, ?)", (u, uid))

    # Update last_checked
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE monitored_profiles SET last_checked=? WHERE id=?",
        (now, profile_id),
    )
    conn.commit()
    conn.close()

    log.info("DB synced: %d followers, %d following recorded for @%s.", len(followers), len(following), target)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\n{'='*55}")
    print(f"  Instagram Sync (Stealth Split Mode)  --  @{TARGET}")
    print(f"{'='*55}\n")

    # 1. Clear session cache and re-import browser cookies
    refresh_session_cache()

    # 2. Load session and build web connection
    L = get_loader()
    sess = create_web_session(L)

    # 3. Resolve target user ID directly from session cookies / context
    log.info("Resolving numeric user ID for '@%s'...", TARGET)
    try:
        target_uid = resolve_target_user_id(L, sess, TARGET)
        log.info("Resolved User ID: %s for @%s", target_uid, TARGET)
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        sys.exit(1)

    # Also save target_uid into user_id_cache
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO user_id_cache (username, user_id) VALUES (?, ?)", (TARGET, target_uid))
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Connection A: Fetch Following
    log.info("Opening Connection A to fetch FOLLOWING...")
    sess_a = create_web_session(L)
    print(f"[1/2] Fetching FOLLOWING of @{TARGET}...")
    following = fetch_list_stealth(sess_a, target_uid, "following")
    sess_a.close()

    # Pause 10 seconds between connections
    log.info("Split Mode: Waiting 10 seconds before opening Connection B...")
    time.sleep(10.0)

    # Connection B: Fetch Followers
    log.info("Opening Connection B to fetch FOLLOWERS...")
    sess_b = create_web_session(L)
    print(f"[2/2] Fetching FOLLOWERS of @{TARGET}...")
    followers = fetch_list_stealth(sess_b, target_uid, "followers")
    sess_b.close()

    follower_set = set(followers.keys())
    following_set = set(following.keys())

    mutual         = follower_set & following_set
    followers_only = follower_set - following_set
    following_only = following_set - follower_set

    print(f"\n{'='*55}")
    print(f"  Results for @{TARGET}")
    print(f"{'='*55}")
    print(f"  Total Followers  : {len(follower_set)}")
    print(f"  Total Following  : {len(following_set)}")
    print(f"  Mutual           : {len(mutual)}")
    print(f"  Followers Only   : {len(followers_only)}")
    print(f"  Following Only   : {len(following_only)}")
    print(f"{'='*55}")

    print("\nSyncing to database...")
    sync_to_db(TARGET, followers, following)
    print(f"\nDone! View your updated dashboard at http://localhost:8501")


if __name__ == "__main__":
    main()
