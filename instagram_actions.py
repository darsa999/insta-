"""
instagram_actions.py
--------------------
Authenticated Instagram actions module for @darsal1a.
Handles session loading, numeric user ID resolution, live unfollow requests,
checkpoint/rate-limit detection, and immediate SQLite database synchronization.

Database helpers and shared constants live in instagram_service.py; this
module owns everything that talks to Instagram over the network.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

# SSL workaround, paths, TARGET_USERNAME and DB helpers are defined once in
# instagram_service and reused here (no duplicated copies).
from instagram_service import (
    SESSION_FILE,
    TARGET_USERNAME,
    get_db,
    get_target_profile_id,
)

log = logging.getLogger("instagram_actions")

WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
IG_APP_ID = "936619743392459"
IG_AJAX_ID = "1009890256"
IG_ASBD_ID = "359341"
# NOTE: x-ig-www-claim is normally issued per session by Instagram. This value
# was copied from a browser session and may be stale.
IG_WWW_CLAIM = "hmac.AR12quedupPYq33BIqNR1dDN3YzOku9HVDFgcIRFSJAxQOox"

_REDIRECT_CODES = (301, 302, 303, 307, 308)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def _load_session_cookies():
    """Read the instaloader .session file and return its cookie jar (raises on failure)."""
    import instaloader

    loader = instaloader.Instaloader(quiet=True)
    loader.load_session_from_file(TARGET_USERNAME, str(SESSION_FILE))
    return loader.context._session.cookies


def load_session() -> tuple[requests.Session | None, str | None, str | None]:
    """
    Load .session file and configure an authenticated requests.Session.
    Returns:
      (session, csrftoken, error_message)
    """
    if not SESSION_FILE.exists():
        return None, None, f"Session file not found at {SESSION_FILE}."

    try:
        cookies = _load_session_cookies()
    except Exception as exc:
        return None, None, f"Failed to load session: {exc}"

    session = requests.Session()
    session.verify = False
    session.cookies.update(cookies)

    csrftoken = cookies.get("csrftoken", "") or ""
    session.headers.update({
        "User-Agent": WEB_USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-IG-App-ID": IG_APP_ID,
        "X-Instagram-AJAX": IG_AJAX_ID,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/",
        "Origin": "https://www.instagram.com",
    })
    if csrftoken:
        session.headers["X-CSRFToken"] = csrftoken

    return session, csrftoken, None


# ---------------------------------------------------------------------------
# User ID resolution
# ---------------------------------------------------------------------------
def _clean_uid(value) -> str | None:
    """Normalise an Instagram pk/id to a string, or None when missing.

    (Previously `str(None)` produced the literal "None", which was cached
    in user_id_cache as if it were a valid ID.)
    """
    if value in (None, "", 0):
        return None
    return str(value)


def _cache_user_id(conn, username: str, uid: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO user_id_cache (username, user_id) VALUES (?, ?)",
        (username, uid),
    )
    conn.commit()


def _lookup_user_id_online(session: requests.Session, username: str) -> str | None:
    """Query Instagram's web endpoints for a username's numeric ID."""
    try:
        resp = session.get(
            "https://www.instagram.com/api/v1/web/search/topsearch/",
            params={"context": "blended", "query": username},
            timeout=10,
        )
        if resp.status_code == 200:
            for item in resp.json().get("users", []):
                u = item.get("user", {})
                if u.get("username", "").lower() == username.lower():
                    uid = _clean_uid(u.get("pk") or u.get("id"))
                    if uid:
                        return uid
    except Exception as e:
        log.debug("Topsearch lookup error for '%s': %s", username, e)

    try:
        resp = session.get(
            "https://www.instagram.com/api/v1/users/web_profile_info/",
            params={"username": username},
            timeout=10,
        )
        if resp.status_code == 200:
            uid = _clean_uid(resp.json().get("data", {}).get("user", {}).get("id"))
            if uid:
                return uid
    except Exception as e:
        log.debug("web_profile_info lookup error for '%s': %s", username, e)

    return None


def resolve_user_id(username: str, session: requests.Session | None = None) -> str | None:
    """
    Resolve username to numeric Instagram user_id.
    Order: own account via ds_user_id cookie -> SQLite cache ->
    following/followers tables -> Instagram web API.
    """
    username = username.strip().lstrip("@")

    # Fast path for the root account: its ID is the ds_user_id cookie.
    if username.lower() == TARGET_USERNAME.lower():
        try:
            jar = session.cookies if session is not None else _load_session_cookies()
            uid = _clean_uid(jar.get("ds_user_id"))
            if uid:
                return uid
        except Exception:
            pass

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id FROM user_id_cache WHERE username = ?", (username,)
        ).fetchone()
        uid = _clean_uid(row["user_id"]) if row else None
        if uid and uid != "None":
            return uid

        for tbl, col in (("following", "following_username"), ("followers", "follower_username")):
            row = conn.execute(
                f"SELECT user_id FROM {tbl} WHERE {col} = ? AND user_id IS NOT NULL AND user_id != ''",
                (username,),
            ).fetchone()
            uid = _clean_uid(row["user_id"]) if row else None
            if uid:
                _cache_user_id(conn, username, uid)
                return uid

        if session is None:
            session, _, _ = load_session()
        if session is None:
            return None

        uid = _lookup_user_id_online(session, username)
        if uid:
            _cache_user_id(conn, username, uid)
        return uid
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Database sync
# ---------------------------------------------------------------------------
def remove_following_from_db(username: str) -> bool:
    """
    Remove record from following table in instagram_tracker.db upon successful unfollow,
    and log an event to follower_events.
    """
    username = username.strip().lstrip("@")
    try:
        conn = get_db()
        try:
            with conn:
                pid = get_target_profile_id(conn)
                cur = conn.execute(
                    "DELETE FROM following WHERE profile_id = ? AND following_username = ?",
                    (pid, username),
                )
                deleted = cur.rowcount > 0
                conn.execute(
                    "INSERT INTO follower_events (profile_id, event_type, username, detected_at) "
                    "VALUES (?, 'unfollowed_by_user', ?, ?)",
                    (pid, username, datetime.now(timezone.utc).isoformat()),
                )
        finally:
            conn.close()
        log.info("Database: Removed @%s from following table (deleted=%s).", username, deleted)
        return True
    except Exception as exc:
        log.error("Database error removing @%s from following: %s", username, exc)
        return False


# ---------------------------------------------------------------------------
# Unfollow
# ---------------------------------------------------------------------------
_BLOCK_MARKERS = (
    ("checkpoint", "Instagram checkpoint required: {msg}", "Checkpoint encountered"),
    ("feedback_required", "Instagram action block (feedback_required): {msg}", "Action blocked"),
    ("challenge_required", "Instagram challenge required: {msg}", "Challenge encountered"),
    ("please wait a few minutes", "Rate limit: Instagram requested waiting a few minutes.", ""),
    ("action_blocked", "Instagram action blocked: {msg}", "Action blocked"),
    ("action blocked", "Instagram action blocked: {msg}", "Action blocked"),
    ("login_required", "Session invalid (login_required). Please re-import browser cookies.", ""),
)


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

    haystack = f"{response_text or ''}\n{msg}".lower()
    for marker, template, default in _BLOCK_MARKERS:
        if marker in haystack:
            return True, template.format(msg=msg or default)

    return False, ""


def _unfollow_headers(csrf_token: str) -> dict[str, str]:
    return {
        "User-Agent": WEB_USER_AGENT,
        "X-CSRFToken": csrf_token,
        "X-IG-App-ID": IG_APP_ID,
        "X-Instagram-AJAX": "1",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/",
        "Origin": "https://www.instagram.com",
        "Content-Type": "application/x-www-form-urlencoded",
        "x-asbd-id": IG_ASBD_ID,
        "x-ig-www-claim": IG_WWW_CLAIM,
    }


def unfollow_user(
    username: str,
    user_id: str | None = None,
    session: requests.Session | None = None,
    csrftoken: str | None = None,
) -> tuple[bool, str, bool]:
    """
    Send unfollow POST request to Instagram.
    Cookies are re-read from .session on each call so a session re-imported
    mid-batch is picked up. `session`/`csrftoken` are accepted for API
    compatibility; `session` is only used as a fallback for ID resolution.

    Returns:
      (success: bool, status_message: str, is_fatal: bool)
    """
    username = username.strip().lstrip("@")

    # 1. Load fresh cookies directly from .session
    if not SESSION_FILE.exists():
        return False, f"Session file not found at {SESSION_FILE}. Please import browser session cookies.", True

    try:
        loader_cookies = _load_session_cookies()
    except Exception as exc:
        return False, f"Failed to load fresh session from {SESSION_FILE}: {exc}", True

    # 2. Verify required cookies
    if not loader_cookies.get("sessionid"):
        return False, "Session error: 'sessionid' cookie missing from .session. Please re-import browser session.", True
    csrf_token = loader_cookies.get("csrftoken") or csrftoken or ""

    fresh_session = requests.Session()
    fresh_session.verify = False
    fresh_session.cookies.update(loader_cookies)

    # 3. Resolve user_id if not provided
    if not user_id:
        user_id = resolve_user_id(username, session=session or fresh_session)
    if not user_id:
        return False, f"Could not resolve numeric user ID for @{username}.", False

    headers = _unfollow_headers(csrf_token)
    payload = {"user_id": str(user_id)}
    endpoints = (
        f"https://www.instagram.com/api/v1/friendships/destroy/{user_id}/",
        f"https://www.instagram.com/web/friendships/{user_id}/unfollow/",
    )

    last_error = ""
    last_fatal = False
    try:
        for endpoint in endpoints:
            try:
                resp = fresh_session.post(
                    endpoint, headers=headers, data=payload, timeout=15, allow_redirects=False,
                )
            except requests.exceptions.TooManyRedirects:
                return False, "Authentication/Session expired (Exceeded redirects). Please re-import browser session.", True
            except requests.exceptions.RequestException as exc:
                last_error, last_fatal = f"Network error sending unfollow for @{username}: {exc}", False
                continue

            status_code = resp.status_code

            if status_code == 200:
                try:
                    data = resp.json() if resp.content else {}
                except ValueError:
                    data = {}

                if data.get("status") == "ok":
                    remove_following_from_db(username)
                    return True, "Success", False
                if data:
                    is_fatal, halt_reason = _check_checkpoint_or_rate_limit(status_code, resp.text, data)
                    msg = data.get("message") or str(data)
                    return False, halt_reason if is_fatal else f"Instagram returned: {msg}", is_fatal
                # 200 with a non-JSON body (e.g. HTML page) — try the next endpoint.
                last_error, last_fatal = f"Instagram returned a non-JSON response (HTTP 200) from {endpoint}.", False
                continue

            if status_code in _REDIRECT_CODES:
                target_location = resp.headers.get("Location", "")
                log.warning(
                    "Unfollow HTTP %d redirect for @%s on %s to target location: %s",
                    status_code, username, endpoint, target_location,
                )
                last_error = f"HTTP {status_code} redirect to {target_location} (Session expired or login required)."
                last_fatal = True
                continue

            if status_code == 429:
                return False, "Rate limit reached (HTTP 429). Instagram is throttling requests.", True

            if status_code in (401, 403):
                return False, f"Authentication/Session expired (HTTP {status_code}). Please re-import browser session cookies.", True

            is_fatal, halt_reason = _check_checkpoint_or_rate_limit(status_code, resp.text, {})
            if is_fatal:
                return False, halt_reason, True

            last_error, last_fatal = f"Instagram error (HTTP {status_code}): {resp.text[:140]}", False
    finally:
        fresh_session.close()

    return False, last_error or f"Unfollow failed for @{username} (no usable response).", last_fatal
