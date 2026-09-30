"""
init_db.py
----------
Initializes the SQLite database for the Instagram Follower Tracker.

Creates the following tables:
  - monitored_profiles : stores Instagram usernames to track
  - followers          : stores follower snapshots per profile
"""

import sqlite3
import os

DB_NAME = "instagram_tracker.db"


def init_db():
    """Create the database and required tables if they do not already exist."""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_NAME)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Enable foreign-key enforcement for this connection
    cursor.execute("PRAGMA foreign_keys = ON;")

    # ------------------------------------------------------------------
    # Table: monitored_profiles
    #   id           – auto-incrementing primary key
    #   username     – Instagram username (must be unique)
    #   last_checked – ISO-8601 timestamp of the last successful scrape
    # ------------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monitored_profiles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    NOT NULL UNIQUE,
            last_checked TEXT
        );
    """)

    # ------------------------------------------------------------------
    # Table: followers
    #   id                – auto-incrementing primary key
    #   profile_id        – FK referencing monitored_profiles.id
    #   follower_username – Instagram username of the follower
    #   profile_pic_path  – local path to the cached profile picture
    #   UNIQUE(profile_id, follower_username) prevents duplicate rows
    # ------------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS followers (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id        INTEGER NOT NULL,
            follower_username TEXT    NOT NULL,
            profile_pic_path  TEXT,
            FOREIGN KEY (profile_id)
                REFERENCES monitored_profiles (id)
                ON DELETE CASCADE,
            UNIQUE (profile_id, follower_username)
        );
    """)

    conn.commit()
    conn.close()

    print(f"[OK] Database initialised successfully at: {db_path}")
    print("[OK] Tables created: monitored_profiles, followers")


if __name__ == "__main__":
    init_db()
