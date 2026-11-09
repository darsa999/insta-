"""
init_db.py
----------
Initializes the SQLite database for the Instagram Follower Tracker.

Uses the single schema definition in instagram_service.py (the previous
standalone version only created `monitored_profiles` and an outdated
`followers` table without user_id, out of sync with the app).
"""

import instagram_service


def init_db() -> None:
    """Create the database, all tables and the target profile row if missing."""
    instagram_service.init_database(force=True)
    print(f"[OK] Database initialised successfully at: {instagram_service.DB_PATH}")
    print("[OK] Tables: monitored_profiles, followers, following, follower_events, user_id_cache")


if __name__ == "__main__":
    init_db()
