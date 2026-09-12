"""Test Admin User Seeding, Password Hashing, and Auth Login Route."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novelvideo.api.app import app
from novelvideo.user_store import authenticate_user, seed_user


def test_seed_admin_and_authenticate() -> None:
    """Verify user seeding and password authentication logic."""
    user = seed_user(
        username="AnsoATC",
        email="ansoatc@gmail.com",
        password="Anso@1234",
        role="admin",
    )
    assert user["username"] == "AnsoATC"
    assert user["email"] == "ansoatc@gmail.com"
    assert user["role"] == "admin"

    # Valid credentials
    auth_ok = authenticate_user("AnsoATC", "Anso@1234")
    assert auth_ok is not None
    assert auth_ok["username"] == "AnsoATC"
    assert auth_ok["role"] == "admin"

    # Email authentication
    auth_email_ok = authenticate_user("ansoatc@gmail.com", "Anso@1234")
    assert auth_email_ok is not None
    assert auth_email_ok["username"] == "AnsoATC"

    # Invalid password
    auth_bad_pass = authenticate_user("AnsoATC", "WrongPassword123")
    assert auth_bad_pass is None


def test_login_api_endpoint() -> None:
    """Verify POST /api/v1/auth/login and subsequent GET /api/v1/auth/me."""
    seed_user(
        username="AnsoATC",
        email="ansoatc@gmail.com",
        password="Anso@1234",
        role="admin",
    )

    with TestClient(app) as client:
        # 1. Login with valid credentials
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "AnsoATC", "password": "Anso@1234"},
        )
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["username"] == "AnsoATC"
        assert body["data"]["role"] == "admin"
        token = resp.cookies.get("st_session")
        assert token is not None

        # 2. Check /auth/me with session cookie
        me_resp = client.get("/api/v1/auth/me", headers={"Cookie": f"st_session={token}"})
        assert me_resp.status_code == 200
        me_body = me_resp.json()
        assert me_body["ok"] is True
        assert me_body["data"]["username"] == "AnsoATC"
        assert me_body["data"]["role"] == "admin"

        # 3. Invalid credentials test
        bad_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "AnsoATC", "password": "WrongPassword"},
        )
        assert bad_resp.status_code == 401
