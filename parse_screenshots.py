"""
parse_screenshots.py
--------------------
Extracts Instagram usernames from follower-list screenshots using EasyOCR
and inserts them into the SQLite database as a baseline.

Usage:
    python parse_screenshots.py <target_username>

Example:
    python parse_screenshots.py darsal1a

Place your screenshots in:
    insta tracker/screenshots/
    Name them anything (e.g. followers_1.png, followers_2.jpg, screen3.png).
    Supported formats: PNG, JPG, JPEG, BMP, WEBP
"""

# ---------------------------------------------------------------------------
# SSL fix — must happen before any network-touching import (easyocr, torch)
# Python 3.14 on Windows sometimes has a broken CA bundle; this patches it.
# ---------------------------------------------------------------------------
import ssl
_orig_create_default_context = ssl.create_default_context
def _patched_create_default_context(*args, **kwargs):
    ctx = _orig_create_default_context(*args, **kwargs)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx
ssl.create_default_context = _patched_create_default_context

import os
import re
import sys
import sqlite3
import logging
from pathlib import Path
import urllib.request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR        = Path(__file__).resolve().parent
DB_PATH         = BASE_DIR / "instagram_tracker.db"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SUPPORTED_EXT   = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

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
# Username filter rules
#
# Instagram usernames:
#   - 1–30 characters
#   - Only lowercase letters, digits, underscores, periods
#   - Must not start or end with a period
#   - Must contain at least one letter or digit
# ---------------------------------------------------------------------------

# Exact phrases that are definitely UI chrome, not usernames
UI_BLACKLIST_EXACT: set[str] = {
    "followers", "following", "follow", "requested", "remove",
    "message", "share", "search", "explore", "notifications",
    "home", "profile", "reel", "reels", "story", "stories",
    "likes", "comments", "tagged", "close", "done", "back",
    "see all", "suggested", "see more", "mutual followers",
    "followed by", "you follow each other",
}

# Regex patterns for text that is clearly NOT a username
NON_USERNAME_PATTERNS: list[re.Pattern] = [
    re.compile(r"^\d+$"),                          # pure numbers
    re.compile(r"^\d[\d,\.]+[kmb]?$", re.I),       # follower counts (e.g. 1.2k, 3,400)
    re.compile(r":\d{2}"),                          # timestamps (HH:MM, etc.)
    re.compile(r"^\d{1,2}[\/\-]\d{1,2}"),          # dates
    re.compile(r"^[^a-z0-9_\.]+$", re.I),          # no alphanumeric at all
    re.compile(r"\s{2,}"),                          # multi-space (UI label, not username)
    re.compile(r"[^a-zA-Z0-9_.@]"),               # contains characters invalid in usernames
    re.compile(r"^\."),                             # starts with period
    re.compile(r"\.$"),                             # ends with period
    re.compile(r"\.{2,}"),                          # consecutive periods
]

# Instagram username validation regex (strict)
IG_USERNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._]{0,28}[a-zA-Z0-9])?$")


def is_valid_username(text: str) -> bool:
    """
    Return True if *text* looks like a plausible Instagram username.

    Applies:
      1. Length check (1–30 chars)
      2. Blacklist of known UI strings
      3. Pattern-based rejection
      4. Instagram username character/format rules
    """
    text = text.strip()

    # Strip leading @ (common in OCR output)
    if text.startswith("@"):
        text = text[1:]

    if not text:
        return False

    # Length
    if not (1 <= len(text) <= 30):
        return False

    # Exact blacklist (case-insensitive)
    if text.lower() in UI_BLACKLIST_EXACT:
        return False

    # Pattern rejection
    for pattern in NON_USERNAME_PATTERNS:
        if pattern.search(text):
            return False

    # Final IG username format check
    return bool(IG_USERNAME_RE.match(text))


def clean_ocr_line(raw: str) -> str:
    """
    Normalise a raw OCR line before validation:
      - Strip whitespace
      - Lower-case (IG usernames are case-insensitive, stored as-is but matched lower)
      - Remove @ prefix
    """
    text = raw.strip()
    if text.startswith("@"):
        text = text[1:]
    return text


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def run_ocr_on_image(reader, image_path: Path) -> list[str]:
    """
    Run EasyOCR on a single image and return a list of filtered usernames.
    """
    log.info("Processing: %s", image_path.name)

    results = reader.readtext(str(image_path), detail=0, paragraph=False)
    # detail=0 → returns plain strings; paragraph=False → one line per detection

    candidates: list[str] = []
    for raw_text in results:
        # Some OCR detections contain multiple words/lines — split them
        for part in re.split(r"[\n\r|]+", raw_text):
            cleaned = clean_ocr_line(part)
            if cleaned and is_valid_username(cleaned):
                candidates.append(cleaned)

    log.info("  Found %d candidate username(s) in %s", len(candidates), image_path.name)
    return candidates


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def get_or_create_profile(conn: sqlite3.Connection, username: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT id FROM monitored_profiles WHERE username = ?", (username,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute(
        "INSERT INTO monitored_profiles (username, last_checked) VALUES (?, NULL)",
        (username,),
    )
    conn.commit()
    log.info("Created monitored_profiles entry for '%s' (id=%d).", username, cur.lastrowid)
    return cur.lastrowid


def insert_usernames(
    conn: sqlite3.Connection,
    profile_id: int,
    usernames: list[str],
) -> tuple[int, int]:
    """
    Bulk-insert usernames into the followers table.
    Returns (inserted_count, skipped_count).
    """
    inserted = skipped = 0
    cur = conn.cursor()
    for username in usernames:
        cur.execute(
            """
            INSERT OR IGNORE INTO followers
                (profile_id, follower_username, profile_pic_path)
            VALUES (?, ?, NULL)
            """,
            (profile_id, username),
        )
        if cur.rowcount > 0:
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    return inserted, skipped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage:   python parse_screenshots.py <target_username>")
        print("Example: python parse_screenshots.py darsal1a")
        sys.exit(1)

    target_username = sys.argv[1].strip().lstrip("@").lower()

    # -- Verify screenshots folder exists ---------------------------------
    if not SCREENSHOTS_DIR.exists():
        print(f"\n[ERROR] Screenshots folder not found: {SCREENSHOTS_DIR}")
        print("Please create it and place your screenshot files inside.")
        sys.exit(1)

    images = [
        p for p in sorted(SCREENSHOTS_DIR.iterdir())
        if p.suffix.lower() in SUPPORTED_EXT
    ]

    if not images:
        print(f"\n[ERROR] No supported images found in '{SCREENSHOTS_DIR}'.")
        print(f"Supported formats: {', '.join(SUPPORTED_EXT)}")
        sys.exit(1)

    log.info("Found %d screenshot(s) to process.", len(images))

    # -- Load EasyOCR (downloads model on first use, ~50 MB) -------------
    print("\n[INFO] Loading EasyOCR model (first run may download ~50 MB)...")
    import easyocr  # imported here so startup is fast if args are wrong

    # Ensure SSL-patched context is also used by urllib inside easyocr
    ssl._create_default_https_context = ssl._create_unverified_context

    reader = easyocr.Reader(
        ["en"],
        gpu=False,
        verbose=False,
        download_enabled=True,   # allow first-time model download
    )
    print("[INFO] EasyOCR ready.\n")

    # -- Run OCR on all screenshots ---------------------------------------
    all_usernames: list[str] = []
    for image_path in images:
        found = run_ocr_on_image(reader, image_path)
        all_usernames.extend(found)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_usernames: list[str] = []
    for u in all_usernames:
        if u not in seen:
            seen.add(u)
            unique_usernames.append(u)

    print(f"\n[RESULT] {len(unique_usernames)} unique username(s) extracted across all screenshots.")

    if not unique_usernames:
        print("[WARN] No valid usernames found. Check your screenshots and try again.")
        sys.exit(0)

    # -- Preview extracted usernames --------------------------------------
    print("\n--- Extracted Usernames Preview ---")
    for i, u in enumerate(unique_usernames, start=1):
        print(f"  {i:>4}. {u}")
    print("-----------------------------------\n")

    # -- Confirm before inserting ----------------------------------------
    answer = input(
        f"Insert these {len(unique_usernames)} username(s) into the database "
        f"as followers of '{target_username}'? [y/N]: "
    ).strip().lower()

    if answer != "y":
        print("Aborted. No changes made to the database.")
        sys.exit(0)

    # -- Write to DB ------------------------------------------------------
    conn = get_db_connection()
    profile_id = get_or_create_profile(conn, target_username)
    inserted, skipped = insert_usernames(conn, profile_id, unique_usernames)
    conn.close()

    print(f"\n[DONE] Inserted: {inserted}  |  Already existed (skipped): {skipped}")
    print(
        f"Database now contains these usernames as the baseline for '{target_username}'.\n"
        "You can now run the live tracker:\n"
        f"    python tracker.py {target_username}\n"
    )


if __name__ == "__main__":
    main()
