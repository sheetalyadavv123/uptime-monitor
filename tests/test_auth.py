# =============================================================================
# tests/test_auth.py  -  REGISTER, LOGIN AND TOKENS
# =============================================================================
from datetime import timedelta

import jwt

from app.config import settings
from app.models import utcnow


# Test: register returns user without password.
async def test_register_returns_user_without_password(client):
    response = await client.post(
        "/api/v1/auth/register", json={"email": "Alice@Example.com", "password": "a-good-password"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"  # stored in lowercase
    assert "password" not in body and "hashed_password" not in body


# Test: register same email twice is rejected.
async def test_register_same_email_twice_is_rejected(client):
    payload = {"email": "alice@example.com", "password": "a-good-password"}
    await client.post("/api/v1/auth/register", json=payload)
    # Different capital letters, same person.
    response = await client.post(
        "/api/v1/auth/register", json={**payload, "email": "ALICE@example.com"}
    )
    assert response.status_code == 409


# Test: register rejects bad input.
async def test_register_rejects_bad_input(client):
    bad_email = await client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": "a-good-password"}
    )
    short_password = await client.post(
        "/api/v1/auth/register", json={"email": "a@example.com", "password": "short"}
    )
    assert bad_email.status_code == 422
    assert short_password.status_code == 422


# Test: login gives token that works.
async def test_login_gives_token_that_works(client):
    await client.post(
        "/api/v1/auth/register", json={"email": "alice@example.com", "password": "a-good-password"}
    )
    login = await client.post(
        "/api/v1/auth/login", data={"username": "alice@example.com", "password": "a-good-password"}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


# Test: login with wrong password or unknown email fails the same way.
async def test_login_with_wrong_password_or_unknown_email_fails_the_same_way(client):
    await client.post(
        "/api/v1/auth/register", json={"email": "alice@example.com", "password": "a-good-password"}
    )
    wrong_password = await client.post(
        "/api/v1/auth/login", data={"username": "alice@example.com", "password": "wrong-password"}
    )
    unknown_email = await client.post(
        "/api/v1/auth/login", data={"username": "nobody@example.com", "password": "a-good-password"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    # Same message, so attackers cannot find out which emails exist.
    assert wrong_password.json() == unknown_email.json()


# Test: protected route needs a token.
async def test_protected_route_needs_a_token(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    garbage = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert garbage.status_code == 401


# Test: expired token is rejected.
async def test_expired_token_is_rejected(client, auth_headers):
    expired = jwt.encode(
        {"sub": "1", "exp": utcnow() - timedelta(minutes=1)}, settings.secret_key, algorithm="HS256"
    )
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


# Test: token signed with another secret is rejected.
async def test_token_signed_with_another_secret_is_rejected(client, auth_headers):
    forged = jwt.encode(
        {"sub": "1", "exp": utcnow() + timedelta(minutes=5)}, "a-different-secret-key-for-testing-only", algorithm="HS256"
    )
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
