"""Local User Database & Auth Session Store for DramaClaw Community Edition."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

from novelvideo.config import STATE_DIR


def get_users_db_path() -> Path:
    """Return the absolute path to the users SQLite database."""
    state_dir = Path(STATE_DIR)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "users.db"


def _get_connection() -> sqlite3.Connection:
    db_path = get_users_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize SQLite tables for users and sessions."""
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        conn.commit()


def hash_password(password: str, salt: str | None = None) -> str:
    """Hash password using PBKDF2-HMAC-SHA256."""
    if not salt:
        salt = os.urandom(16).hex()
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    ).hex()
    return f"pbkdf2:sha256:100000${salt}${hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored PBKDF2 hash."""
    if not stored_hash or not stored_hash.startswith("pbkdf2:sha256:"):
        return False
    try:
        parts = stored_hash.split("$")
        if len(parts) != 3:
            return False
        header, salt, expected_hex = parts
        computed_hex = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100000,
        ).hex()
        return hmac_compare(computed_hex, expected_hex)
    except Exception:
        return False


def hmac_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison."""
    import secrets
    return secrets.compare_digest(a, b)


def seed_user(
    username: str = "AnsoATC",
    email: str = "ansoatc@gmail.com",
    password: str = "Anso@1234",
    role: str = "admin",
) -> Dict[str, Any]:
    """Create or update user account."""
    init_db()
    pwd_hash = hash_password(password)
    now = time.time()

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, email FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
            (username, email),
        )
        existing = cursor.fetchone()

        if existing:
            user_id = existing["id"]
            cursor.execute(
                """
                UPDATE users
                SET username = ?, email = ?, password_hash = ?, role = ?, updated_at = ?
                WHERE id = ?
                """,
                (username, email, pwd_hash, role, now, user_id),
            )
        else:
            import uuid
            user_id = f"usr_{uuid.uuid4().hex[:12]}"
            cursor.execute(
                """
                INSERT INTO users (id, username, email, password_hash, role, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, email, pwd_hash, role, now, now),
            )
        conn.commit()

        return {
            "id": user_id,
            "username": username,
            "email": email,
            "role": role,
            "updated_at": now,
        }


def authenticate_user(username_or_email: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate user with username/email and password."""
    init_db()
    clean_identifier = (username_or_email or "").strip().lower()
    if not clean_identifier or not password:
        return None

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE LOWER(username) = ? OR LOWER(email) = ?",
            (clean_identifier, clean_identifier),
        )
        row = cursor.fetchone()
        if not row:
            return None

        user = dict(row)
        if verify_password(password, user["password_hash"]):
            return {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"],
            }
    return None


def create_session(user_id: str, username: str, role: str, ttl_seconds: int = 7 * 86400) -> str:
    """Create session token for authenticated user."""
    init_db()
    import uuid
    token = f"st_sess_{uuid.uuid4().hex}"
    now = time.time()
    expires_at = now + ttl_seconds

    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sessions (token, user_id, username, role, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (token, user_id, username, role, now, expires_at),
        )
        conn.commit()
    return token


def get_session(token: str | None) -> Optional[Dict[str, Any]]:
    """Get active session by token."""
    if not token or not token.strip():
        return None
    init_db()
    now = time.time()
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM sessions WHERE token = ? AND expires_at > ?",
            (token.strip(), now),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def revoke_session(token: str) -> None:
    """Revoke session token."""
    if not token:
        return
    init_db()
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (token.strip(),))
        conn.commit()
