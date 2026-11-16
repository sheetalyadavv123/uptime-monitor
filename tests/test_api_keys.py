# =============================================================================
# tests/test_api_keys.py  -  API KEYS (USED BY THE MCP SERVER)
# =============================================================================
from app.services import api_keys as api_key_service


# Test: create key shows secret once.
async def test_create_key_shows_secret_once(client, auth_headers):
    created = await client.post("/api/v1/api-keys", json={"name": "Claude"}, headers=auth_headers)
    assert created.status_code == 201
    body = created.json()
    assert body["key"].startswith("upm_")
    assert body["key_prefix"] == body["key"][:8]

    # Listing shows the key WITHOUT the secret.
    listed = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "key" not in listed.json()[0]


# Test: secret is not stored in plain text.
async def test_secret_is_not_stored_in_plain_text(client, auth_headers, session):
    created = await client.post("/api/v1/api-keys", json={"name": "Claude"}, headers=auth_headers)
    secret = created.json()["key"]

    from sqlalchemy import select

    from app.models import ApiKey

    stored = await session.scalar(select(ApiKey))
    assert secret not in (stored.key_hash, stored.key_prefix)
    assert len(stored.key_hash) == 64  # a SHA-256 hash


# Test: key lookup works and unknown key fails.
async def test_key_lookup_works_and_unknown_key_fails(client, auth_headers, session):
    created = await client.post("/api/v1/api-keys", json={"name": "Claude"}, headers=auth_headers)
    secret = created.json()["key"]

    assert await api_key_service.find_user_id_by_key(session, secret) is not None
    assert await api_key_service.find_user_id_by_key(session, "upm_not-a-real-key") is None


# Test: deleted key stops working.
async def test_deleted_key_stops_working(client, auth_headers, session):
    created = (await client.post("/api/v1/api-keys", json={"name": "Claude"}, headers=auth_headers)).json()

    deleted = await client.delete(f"/api/v1/api-keys/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    assert await api_key_service.find_user_id_by_key(session, created["key"]) is None


# Test: cannot delete someone elses key.
async def test_cannot_delete_someone_elses_key(client, auth_headers, other_headers):
    created = (await client.post("/api/v1/api-keys", json={"name": "Claude"}, headers=auth_headers)).json()
    response = await client.delete(f"/api/v1/api-keys/{created['id']}", headers=other_headers)
    assert response.status_code == 404


# Test: api key cannot be used on the rest api.
async def test_api_key_cannot_be_used_on_the_rest_api(client, auth_headers):
    # API keys are only for the MCP server. A key sent to a REST route is not a login token.
    created = (await client.post("/api/v1/api-keys", json={"name": "Claude"}, headers=auth_headers)).json()
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {created['key']}"})
    assert response.status_code == 401
