"""
tracker.py
----------
Instagram Follower Tracker — two modes in one script.
"""

# ---------------------------------------------------------------------------
# SSL fix — patch BEFORE any network-touching import (requests, urllib3)
# Python 3.14 on Windows can have a broken CA bundle; this disables
# certificate verification globally so instaloader can reach Instagram.
# ---------------------------------------------------------------------------
import ssl
import urllib3

ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Monkey-patch requests so every Session it creates skips SSL verification
try:
    import requests
    _OrigSession = requests.Session

    class _NoVerifySession(_OrigSession):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.verify = False

    requests.Session = _NoVerifySession  # type: ignore[misc]
except Exception:
    pass  # If requests isn't available yet, continue

import os
import sys
import time
import random
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

import instaloader
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR     = Path(__file__).resolve().parent
DB_PATH      = BASE_DIR / "instagram_tracker.db"
PICS_DIR     = BASE_DIR / "profile_pics"
SESSION_FILE = BASE_DIR / ".session"   # cached login session

# Polite delay range (seconds) between requests to mimic human behaviour
DELAY_MIN = 2.0
DELAY_MAX = 5.0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------

_SEP_WIDE  = "=" * 60
_SEP_THIN  = "-" * 60


def _section(title: str) -> None:
    """Print a bold section header."""
    print(f"\n{_SEP_WIDE}")
    print(f"  {title}")
    print(_SEP_WIDE)


def _list_users(users: set[str], indent: int = 4) -> None:
    """Print a sorted list of usernames, or a '(none)' placeholder."""
    pad = " " * indent
    if not users:
        print(f"{pad}(none)")
        return
    for u in sorted(users):
        print(f"{pad}• {u}")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db_connection() -> sqlite3.Connection:
    """Return a sqlite3 connection with foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def get_or_create_profile(conn: sqlite3.Connection, username: str) -> int:
    """
    Return the profile_id for *username*, inserting a new row if needed.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM monitored_profiles WHERE username = ?", (username,)
    )
    row = cur.fetchone()
    if row:
        return row["id"]

    cur.execute(
        "INSERT INTO monitored_profiles (username, last_checked) VALUES (?, NULL)",
        (username,),
    )
    conn.commit()
    log.info("Added '%s' to monitored_profiles (id=%d).", username, cur.lastrowid)
    return cur.lastrowid


def get_stored_followers(conn: sqlite3.Connection, profile_id: int) -> set[str]:
    """Return the set of follower usernames stored for *profile_id*."""
    cur = conn.execute(
        "SELECT follower_username FROM followers WHERE profile_id = ?",
        (profile_id,),
    )
    return {row["follower_username"] for row in cur.fetchall()}


def insert_follower(
    conn: sqlite3.Connection,
    profile_id: int,
    username: str,
    pic_path: str | None,
) -> None:
    """Insert a follower row, ignoring duplicates."""
    conn.execute(
        """
        INSERT OR IGNORE INTO followers
            (profile_id, follower_username, profile_pic_path)
        VALUES (?, ?, ?)
        """,
        (profile_id, username, pic_path),
    )
    conn.commit()


def delete_follower(conn: sqlite3.Connection, profile_id: int, username: str) -> None:
    """Remove a follower row from the database."""
    conn.execute(
        "DELETE FROM followers WHERE profile_id = ? AND follower_username = ?",
        (profile_id, username),
    )
    conn.commit()


def update_last_checked(conn: sqlite3.Connection, profile_id: int) -> None:
    """Stamp the current UTC time on the monitored_profiles row."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE monitored_profiles SET last_checked = ? WHERE id = ?",
        (now, profile_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Instaloader helpers
# ---------------------------------------------------------------------------

def build_loader() -> instaloader.Instaloader:
    """
    Create and return a configured Instaloader instance.
    Downloads are directed to profile_pics/, quiet mode suppresses spam.
    """
    return instaloader.Instaloader(
        download_pictures=True,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
        dirname_pattern=str(PICS_DIR / "{target}"),
        filename_pattern="{profile}_pic",
        max_connection_attempts=3,
    )


def login(loader: instaloader.Instaloader, username: str, password: str) -> None:
    """
    Log into Instagram, reusing a cached session when available to reduce
    the risk of triggering security checks on repeated logins.
    """
    session_path = str(SESSION_FILE)
    try:
        loader.load_session_from_file(username, session_path)
        log.info("Session loaded from cache for '%s'.", username)
    except FileNotFoundError:
        log.info("No cached session — logging in fresh.")
        loader.login(username, password)
        loader.save_session_to_file(session_path)
        log.info("Session cached to '%s'.", session_path)
    except Exception as exc:
        log.warning("Could not load cached session (%s). Logging in fresh.", exc)
        loader.login(username, password)
        loader.save_session_to_file(session_path)


def download_profile_pic(
    loader: instaloader.Instaloader,
    follower_username: str,
) -> str | None:
    """
    Download the HD profile picture for *follower_username*.

    Returns the local file path on success, or None on failure.
    Saved to:  profile_pics/<follower_username>/<follower_username>_pic.jpg
    """
    try:
        profile = instaloader.Profile.from_username(loader.context, follower_username)
        target_dir = PICS_DIR / follower_username
        target_dir.mkdir(parents=True, exist_ok=True)
        loader.download_profilepic(profile)
        candidates = sorted(target_dir.glob(f"{follower_username}_pic*.jpg"))
        return str(candidates[-1]) if candidates else None
    except instaloader.exceptions.ProfileNotExistsException:
        log.warning("Profile '%s' does not exist — skipping pic.", follower_username)
        return None
    except Exception as exc:
        log.warning("Could not download pic for '%s': %s", follower_username, exc)
        return None


def polite_sleep(label: str = "") -> None:
    """Sleep for a random human-like duration to avoid rate-limiting."""
    delay = random.uniform(DELAY_MIN, DELAY_MAX)
    log.debug("Sleeping %.1fs %s", delay, label)
    time.sleep(delay)




# ---------------------------------------------------------------------------
# Instagram Mobile API v1 helpers (bypasses instaloader's broken GraphQL)
# ---------------------------------------------------------------------------

# Headers that mimic the Instagram Android app — accepted by the v1 REST API
_IG_HEADERS = {
    "User-Agent": (
        "Instagram 275.0.0.27.98 Android (29/10; 420dpi; 1080x2400; "
        "samsung; SM-G991B; o1s; exynos2100; en_US; 458229237)"
    ),
    "Accept-Language": "en-US",
    "Accept-Encoding": "gzip, deflate",
    "X-IG-App-ID": "936619743392459",
}


def _ig_api_session(loader: instaloader.Instaloader) -> "requests.Session":
    """
    Build a requests.Session pre-loaded with the Instaloader cookies and
    the Instagram mobile app headers.
    """
    s = requests.Session()
    s.verify = False
    s.cookies.update(loader.context._session.cookies)
    s.headers.update(_IG_HEADERS)
    # Add CSRF token from cookies
    csrf = loader.context._session.cookies.get("csrftoken", "")
    if csrf:
        s.headers["X-CSRFToken"] = csrf
    return s


def _get_user_id(session: "requests.Session", username: str) -> str | None:
    """
    Resolve a username to a numeric Instagram user-id.
    Tries three independent methods with separate rate-limit buckets.
    """
    import re as _re

    # ----------------------------------------------------------------
    # Method 1 — Profile page HTML scrape (uses browser cookies,
    #            completely separate from API rate limits)
    # ----------------------------------------------------------------
    log.info("Method 1: scraping profile page HTML for '@%s'...", username)
    try:
        web_session = requests.Session()
        web_session.verify = False
        web_session.cookies.update(session.cookies)
        web_session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        resp = web_session.get(
            f"https://www.instagram.com/{username}/",
            timeout=15,
            allow_redirects=True,
        )
        if resp.status_code == 200:
            html = resp.text
            # Instagram embeds user data in <script> tags as JSON
            # Pattern matches: "id":"46754714624" or "pk":46754714624
            for pattern in [
                r'"id"\s*:\s*"(\d{5,})"',
                r'"pk"\s*:\s*(\d{5,})',
                r'"profilePage_(\d{5,})"',
            ]:
                m = _re.search(pattern, html)
                if m:
                    uid = m.group(1)
                    log.info("Method 1 success: user_id=%s for '@%s'", uid, username)
                    return uid
            log.warning("Method 1: could not find user_id in page HTML for '@%s'.", username)
        else:
            log.warning("Method 1: HTTP %d fetching profile page.", resp.status_code)
    except Exception as exc:
        log.warning("Method 1 error: %s", exc)

    # ----------------------------------------------------------------
    # Method 2 — /api/v1/users/{username}/usernameinfo/  (mobile API)
    # ----------------------------------------------------------------
    log.info("Method 2: usernameinfo endpoint for '@%s'...", username)
    url_a = f"https://i.instagram.com/api/v1/users/{username}/usernameinfo/"
    try:
        resp = session.get(url_a, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            pk = data.get("user", {}).get("pk") or data.get("user", {}).get("id")
            if pk:
                log.info("Method 2 success: user_id=%s for '@%s'", pk, username)
                return str(pk)
        log.warning("Method 2: HTTP %d / status=%s",
                    resp.status_code, resp.json().get("status", "?") if resp.content else "?")
    except Exception as exc:
        log.warning("Method 2 error: %s", exc)

    # ----------------------------------------------------------------
    # Method 3 — web_profile_info with backoff (last resort)
    # ----------------------------------------------------------------
    log.info("Method 3: web_profile_info with backoff for '@%s'...", username)
    url_b = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    for attempt in range(1, 4):
        try:
            resp = session.get(url_b, timeout=15)
        except Exception as exc:
            log.error("Method 3 request error: %s", exc)
            break
        if resp.status_code == 200:
            try:
                uid = str(resp.json()["data"]["user"]["id"])
                log.info("Method 3 success: user_id=%s for '@%s'", uid, username)
                return uid
            except (KeyError, TypeError) as exc:
                log.error("Method 3 JSON parse error: %s", exc)
                break
        elif resp.status_code == 429:
            wait = 30 * attempt
            log.warning("Method 3: rate-limited, waiting %ds (attempt %d/3)...", wait, attempt)
            time.sleep(wait)
        else:
            log.warning("Method 3: HTTP %d — giving up.", resp.status_code)
            break

    log.error("All methods failed to resolve user-id for '@%s'.", username)
    return None


def _fetch_user_list_v1(
    session: "requests.Session",
    user_id: str,
    mode: str,          # "followers" | "following"
    polite_every: int = 20,
) -> set[str]:
    """
    Page through Instagram's mobile API to collect all followers or followees.

    Endpoints:
      followers : GET /api/v1/friendships/{id}/followers/
      following : GET /api/v1/friendships/{id}/following/
    """
    endpoint  = (
        f"https://i.instagram.com/api/v1/friendships/{user_id}/followers/"
        if mode == "followers"
        else f"https://i.instagram.com/api/v1/friendships/{user_id}/following/"
    )
    result:  set[str] = set()
    next_id: str | None = None
    label   = mode.capitalize()

    while True:
        params: dict = {"count": 200}
        if next_id:
            params["max_id"] = next_id

        try:
            resp = session.get(endpoint, params=params, timeout=20)
        except Exception as exc:
            log.error("Request error while fetching %s: %s", mode, exc)
            break

        if resp.status_code == 401:
            log.error("401 Unauthorized fetching %s — session may have expired.", mode)
            break
        if resp.status_code != 200:
            log.warning("HTTP %d fetching %s (page max_id=%s) — stopping.",
                        resp.status_code, mode, next_id)
            break

        data  = resp.json()
        users = data.get("users", [])
        for u in users:
            result.add(u["username"])

        count = len(result)
        if count % polite_every == 0 and count > 0:
            log.info("  %s fetched so far: %d", label, count)

        next_id = data.get("next_max_id") or data.get("next_max_id", None)
        if not next_id:
            break   # no more pages

        polite_sleep(f"(after {count} {mode})")

    log.info("%s total: %d", label, len(result))
    return result


# ---------------------------------------------------------------------------
# MODE 1 — Profile Analysis  (--analyze)
# ---------------------------------------------------------------------------

def analyze_profile(loader: instaloader.Instaloader, target_username: str) -> None:
    """
    Fetch followers and following for *target_username* via Instagram's
    mobile REST API v1 (bypasses instaloader's broken GraphQL endpoints),
    then compute set operations to produce a clean categorised report.

    Does NOT modify the database.
    """
    print(f"\nFetching profile: @{target_username}")
    print(_SEP_THIN)

    # Build a mobile-API session from the stored cookies
    session = _ig_api_session(loader)

    # -- Resolve numeric user-id ------------------------------------------
    log.info("Resolving user-id for '@%s'...", target_username)
    user_id = _get_user_id(session, target_username)
    if not user_id:
        log.error("Could not resolve '@%s'. Check the username and try again.",
                  target_username)
        return
    log.info("User-id for '@%s': %s", target_username, user_id)

    # -- Fetch followers --------------------------------------------------
    print(f"\n[1/2] Fetching FOLLOWERS of @{target_username}...")
    followers: set[str] = _fetch_user_list_v1(session, user_id, "followers")

    # -- Fetch following --------------------------------------------------
    print(f"\n[2/2] Fetching FOLLOWING of @{target_username}...")
    following: set[str] = _fetch_user_list_v1(session, user_id, "following")

    # -- Set operations ---------------------------------------------------
    mutual         : set[str] = followers.intersection(following)
    followers_only : set[str] = followers - following
    following_only : set[str] = following - followers

    # =====================================================================
    # REPORT
    # =====================================================================

    print(f"\n\n{'#' * 60}")
    print(f"  PROFILE ANALYSIS  --  @{target_username}")
    print(f"{'#' * 60}")

    # Summary table
    print(f"\n  {'Category':<33} {'Count':>6}")
    print(f"  {_SEP_THIN}")
    print(f"  {'Total Followers':<33} {len(followers):>6}")
    print(f"  {'Total Following':<33} {len(following):>6}")
    print(f"  {_SEP_THIN}")
    print(f"  {'Mutual (two-way connections)':<33} {len(mutual):>6}")
    print(f"  {'Followers only (no follow-back)':<33} {len(followers_only):>6}")
    print(f"  {'Following only (not followed back)':<33} {len(following_only):>6}")

    # Category 1: All Followers
    _section(f"FOLLOWERS  ({len(followers)})  -- users who follow @{target_username}")
    _list_users(followers)

    # Category 2: All Following
    _section(f"FOLLOWING  ({len(following)})  -- users @{target_username} follows")
    _list_users(following)

    # Category 3: Mutual
    _section(
        f"MUTUAL FOLLOWERS  ({len(mutual)})  "
        "-- two-way connections  "
        "[followers & following]"
    )
    _list_users(mutual)

    # Bonus: one-way only
    _section(
        f"FOLLOWERS ONLY  ({len(followers_only)})  "
        f"-- follow @{target_username} but NOT followed back"
    )
    _list_users(followers_only)

    _section(
        f"FOLLOWING ONLY  ({len(following_only)})  "
        f"-- @{target_username} follows but they DON'T follow back"
    )
    _list_users(following_only)

    print(f"\n{_SEP_WIDE}")
    print(f"  Analysis complete for @{target_username}")
    print(_SEP_WIDE + "\n")


# ---------------------------------------------------------------------------
# MODE 2 — Follower Diff Tracker  (default)
# ---------------------------------------------------------------------------

def track_profile(loader: instaloader.Instaloader, target_username: str) -> None:
    """
    Main diff-tracking function.

    1. Upsert *target_username* in monitored_profiles.
    2. Fetch live followers from Instagram.
    3. Compare with stored followers.
    4. Handle first-run (baseline) or subsequent run (diff) accordingly.
    5. Update last_checked timestamp.
    """
    PICS_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db_connection()

    # -- 1. Ensure the profile is tracked ---------------------------------
    profile_id = get_or_create_profile(conn, target_username)
    log.info("Tracking '@%s' (profile_id=%d).", target_username, profile_id)

    # -- 2. Fetch live followers ------------------------------------------
    log.info("Fetching live followers for '@%s' from Instagram...", target_username)
    try:
        target_profile = instaloader.Profile.from_username(
            loader.context, target_username
        )
    except instaloader.exceptions.ProfileNotExistsException:
        log.error("Profile '@%s' does not exist on Instagram.", target_username)
        conn.close()
        return

    live_followers: set[str] = set()
    try:
        for follower in target_profile.get_followers():
            live_followers.add(follower.username)
            if len(live_followers) % 10 == 0:
                polite_sleep(f"(fetched {len(live_followers)} followers so far)")
    except instaloader.exceptions.LoginRequiredException:
        log.error("Fetching followers requires a logged-in session.")
        conn.close()
        return

    log.info("Live follower count: %d", len(live_followers))

    # -- 3. Fetch stored followers ----------------------------------------
    stored_followers = get_stored_followers(conn, profile_id)
    log.info("Stored follower count: %d", len(stored_followers))

    # -- 4 & 5. First run vs. subsequent run ------------------------------
    if not stored_followers:
        # FIRST RUN — establish baseline
        print(
            f"\n[BASELINE] First run for '@{target_username}'. "
            f"Saving {len(live_followers)} followers as the baseline.\n"
        )
        for idx, username in enumerate(live_followers, start=1):
            pic_path = download_profile_pic(loader, username)
            insert_follower(conn, profile_id, username, pic_path)
            print(f"  [saved] {username} ({idx}/{len(live_followers)})")
            polite_sleep(f"after saving {username}")

        print(
            f"\n[BASELINE] Done. {len(live_followers)} followers saved. "
            "Future runs will detect changes.\n"
        )

    else:
        # SUBSEQUENT RUN — diff old vs. new
        new_followers = live_followers - stored_followers
        unfollowers   = stored_followers - live_followers

        print(f"\n[DIFF] Results for '@{target_username}':")
        print(
            f"  Live: {len(live_followers)}  |  Stored: {len(stored_followers)}  "
            f"|  New: {len(new_followers)}  |  Unfollowed: {len(unfollowers)}\n"
        )

        for username in sorted(new_followers):
            pic_path = download_profile_pic(loader, username)
            insert_follower(conn, profile_id, username, pic_path)
            print(f"  [+] New Follower: {username}")
            polite_sleep(f"after processing new follower {username}")

        for username in sorted(unfollowers):
            pic_file = PICS_DIR / username / f"{username}_pic.jpg"
            if pic_file.exists():
                pic_file.unlink()
                log.debug("Deleted local pic for '%s'.", username)
            delete_follower(conn, profile_id, username)
            print(f"  [-] Unfollower: {username}")

        if not new_followers and not unfollowers:
            print("  [=] No changes detected since last run.")

        print()

    # -- 6. Stamp last_checked -------------------------------------------
    update_last_checked(conn, profile_id)
    log.info("Updated last_checked for '@%s'.", target_username)

    conn.close()
    log.info("Tracking complete for '@%s'.", target_username)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

    load_dotenv(BASE_DIR / ".env")
    ig_username = os.getenv("INSTAGRAM_USERNAME", "darsal1a").strip()
    ig_password = os.getenv("INSTAGRAM_PASSWORD", "").strip()

    if not args or args[0].startswith("-h"):
        target_username = ig_username
        analyze_mode = "--analyze" in args
        if "-h" in args or "--help" in args:
            print("Usage:")
            print("  python tracker.py [target_username] [--analyze]")
            print()
            print("Modes:")
            print("  --analyze   Profile analysis: followers / following / mutual")
            print("  (default)   Diff tracker:     detect new followers & unfollowers")
            print()
            print("Examples:")
            print("  python tracker.py darsal1a --analyze")
            print("  python tracker.py darsal1a")
            sys.exit(0)
    else:
        target_username = args[0].strip().lstrip("@") if not args[0].startswith("--") else ig_username
        analyze_mode    = "--analyze" in args

    if not ig_username or not ig_password:
        log.error("INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD must be set in .env")
        sys.exit(1)

    # Build loader and log in (shared for both modes)
    loader = build_loader()
    log.info("Logging into Instagram as '%s'...", ig_username)
    login(loader, ig_username, ig_password)

    if analyze_mode:
        analyze_profile(loader, target_username)
    else:
        track_profile(loader, target_username)


if __name__ == "__main__":
    main()
