# =============================================================================
# tests/helpers.py  -  SMALL HELPER FUNCTIONS USED BY SEVERAL TEST FILES
# =============================================================================
# Plain functions and classes (not fixtures) that make tests shorter.
# Import them like:  from tests.helpers import create_monitor
# =============================================================================

import json

import httpx


# Registers a user and logs in. Returns the headers to send with later requests.
async def register_and_login(client: httpx.AsyncClient, email: str) -> dict:
    password = "a-good-password"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    response = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# Creates a monitor through the API and returns its JSON.
async def create_monitor(client: httpx.AsyncClient, headers: dict, **overrides) -> dict:
    body = {"name": "Test site", "url": "https://site.test/", **overrides}
    response = await client.post("/api/v1/monitors", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# Builds a fake website client. `handler` decides what answer the "website" gives.
# Example: make_mock_client(lambda request: httpx.Response(200))
def make_mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# A fake alert receiver that remembers every message it got.
class AlertCatcher:
    # Creates the receiver and a client that sends everything to it.
    def __init__(self):
        self.messages: list[dict] = []
        self.client = make_mock_client(self._handler)

    # Called for every message "sent" to the fake receiver: remember it and answer 200 OK.
    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.messages.append(json.loads(request.content))
        return httpx.Response(200)
