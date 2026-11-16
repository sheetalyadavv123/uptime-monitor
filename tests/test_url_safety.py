# =============================================================================
# tests/test_url_safety.py  -  BLOCKING PRIVATE ADDRESSES (SSRF PROTECTION)
# =============================================================================
# In all other tests ALLOW_PRIVATE_URLS is true. Here we turn the protection
# ON to prove that it works.
# =============================================================================
import pytest

from app.config import settings
from app.errors import InvalidInputError
from app.services.url_safety import ensure_public_url
from tests.helpers import create_monitor


# Runs before every test in this file: turns the SSRF protection ON (it is off in other tests).
@pytest.fixture(autouse=True)
def protection_on(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_urls", False)


# Test: private addresses are blocked.
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1:8000/",
        "http://10.0.0.5/",
        "http://192.168.1.1/admin",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata address
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
async def test_private_addresses_are_blocked(url):
    with pytest.raises(InvalidInputError):
        await ensure_public_url(url)


# Test: public ip is allowed.
async def test_public_ip_is_allowed():
    await ensure_public_url("http://8.8.8.8/")  # no error means "allowed"


# Test: unknown host is rejected.
async def test_unknown_host_is_rejected():
    with pytest.raises(InvalidInputError):
        await ensure_public_url("http://this-host-does-not-exist.invalid/")


# Test: api rejects a private monitor url.
async def test_api_rejects_a_private_monitor_url(client, auth_headers):
    response = await client.post(
        "/api/v1/monitors", json={"name": "evil", "url": "http://127.0.0.1:5432/"}, headers=auth_headers
    )
    assert response.status_code == 422
    assert "Private" in response.json()["detail"]


# Test: api rejects a private webhook url.
async def test_api_rejects_a_private_webhook_url(client, auth_headers):
    response = await client.post(
        "/api/v1/monitors",
        json={"name": "x", "url": "http://8.8.8.8/", "alert_webhook_url": "http://localhost/hook"},
        headers=auth_headers,
    )
    assert response.status_code == 422


# Test: changing url to a private one is rejected.
async def test_changing_url_to_a_private_one_is_rejected(client, auth_headers):
    monitor = await create_monitor(client, auth_headers, url="http://8.8.8.8/")
    response = await client.patch(
        f"/api/v1/monitors/{monitor['id']}", json={"url": "http://192.168.0.1/"}, headers=auth_headers
    )
    assert response.status_code == 422


# Test: checker refuses to request a private address.
async def test_checker_refuses_to_request_a_private_address():
    # Even if a private URL got into the database, the checker itself refuses to call it.
    from app.services.checks import perform_http_check

    outcome = await perform_http_check("http://127.0.0.1:9/", 200, 2)
    assert outcome.is_up is False
    assert "Private" in outcome.error
