# =============================================================================
# tests/test_mcp.py  -  THE MCP SERVER, TESTED LIKE A REAL AI TOOL WOULD USE IT
# =============================================================================
# We start the whole app (including the MCP part), then connect with a real MCP
# client over HTTP, sending a real API key in the Authorization header.
# This proves that: authentication works, every tool works, and users stay
# isolated from each other.
#
# Note: FastMCP's client uses a library called `httpx2` internally (a newer
# fork of httpx), which is why you see it below.
# =============================================================================
import asyncio

import httpx2
import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

from app.main import app
from app.services.checks import CheckOutcome
from tests.helpers import create_monitor


# Starts the app's startup steps ONCE for all MCP tests (the MCP server needs
# them to run). `scope="session"` means "do this one time, not per test".
#
# The startup and shutdown steps must happen inside the SAME async task, so we
# run them in one background task and ask it to stop when the tests are done.
@pytest_asyncio.fixture(scope="session")
async def running_app():
    started = asyncio.Event()
    stop = asyncio.Event()

    # Runs the app's startup, waits until told to stop, then runs the app's shutdown.
    async def run_app_lifespan():
        async with app.router.lifespan_context(app):
            started.set()
            await stop.wait()

    task = asyncio.create_task(run_app_lifespan())
    await started.wait()
    yield
    stop.set()
    await task


# Tells the MCP client to talk to our app directly in memory instead of over a network.
def _in_memory_client_factory(headers=None, timeout=None, auth=None, **kwargs):
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=True,
    )


# Builds an MCP client that sends the given API key.
def mcp_client_for(api_key: str) -> Client:
    transport = StreamableHttpTransport(
        "http://test/mcp", auth=api_key, httpx_client_factory=_in_memory_client_factory
    )
    return Client(transport)


# Creates an API key through the REST API.
async def make_api_key(client, headers) -> str:
    response = await client.post("/api/v1/api-keys", json={"name": "test"}, headers=headers)
    return response.json()["key"]


# Calls a tool and returns its structured result.
# Tools that return a list are wrapped by FastMCP as {"result": [...]}.
async def call(mcp_client: Client, tool: str, **arguments):
    result = await mcp_client.call_tool(tool, arguments)
    content = result.structured_content
    return content["result"] if isinstance(content, dict) and list(content) == ["result"] else content


# An MCP client for alice, already connected.
@pytest_asyncio.fixture
async def alice(running_app, client, auth_headers):
    async with mcp_client_for(await make_api_key(client, auth_headers)) as mcp_client:
        yield mcp_client


# ----- Authentication --------------------------------------------------------


# Test: missing or wrong api key is rejected.
async def test_missing_or_wrong_api_key_is_rejected(running_app, client):
    with pytest.raises(Exception):
        async with mcp_client_for("upm_this-key-does-not-exist") as bad_client:
            await bad_client.list_tools()

    # No Authorization header at all.
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as raw:
        response = await raw.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 401


# Test: a login token is not accepted as an api key.
async def test_a_login_token_is_not_accepted_as_an_api_key(running_app, auth_headers):
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    with pytest.raises(Exception):
        async with mcp_client_for(token) as wrong_client:
            await wrong_client.list_tools()


# Test: revoked key stops working.
async def test_revoked_key_stops_working(running_app, client, auth_headers):
    created = (await client.post("/api/v1/api-keys", json={"name": "temp"}, headers=auth_headers)).json()
    await client.delete(f"/api/v1/api-keys/{created['id']}", headers=auth_headers)

    with pytest.raises(Exception):
        async with mcp_client_for(created["key"]) as revoked_client:
            await revoked_client.list_tools()


# ----- Discovery -------------------------------------------------------------


# Test: server offers the expected tools resource and prompt.
async def test_server_offers_the_expected_tools_resource_and_prompt(alice):
    tools = {tool.name for tool in await alice.list_tools()}
    assert tools == {
        "list_monitors", "get_monitor", "add_monitor", "pause_monitor", "resume_monitor",
        "delete_monitor", "check_now", "get_recent_checks", "get_incidents", "get_uptime_report",
    }
    assert [str(r.uri) for r in await alice.list_resources()] == ["uptime://summary"]
    assert [p.name for p in await alice.list_prompts()] == ["investigate_incident"]


# Test: every tool has a description for the ai.
async def test_every_tool_has_a_description_for_the_ai(alice):
    for tool in await alice.list_tools():
        assert tool.description and len(tool.description) > 20, tool.name


# ----- Tools -----------------------------------------------------------------


# Test: add and list monitors.
async def test_add_and_list_monitors(alice):
    added = await call(alice, "add_monitor", name="My site", url="https://site.test/", interval_seconds=120)
    assert added["name"] == "My site" and added["interval_seconds"] == 120

    listed = await call(alice, "list_monitors")
    assert [m["name"] for m in listed] == ["My site"]
    assert (await call(alice, "get_monitor", monitor_id=added["id"]))["url"] == "https://site.test/"


# Test: pause resume and delete.
async def test_pause_resume_and_delete(alice):
    monitor = await call(alice, "add_monitor", name="x", url="https://site.test/")

    assert (await call(alice, "pause_monitor", monitor_id=monitor["id"]))["is_active"] is False
    assert (await call(alice, "resume_monitor", monitor_id=monitor["id"]))["is_active"] is True

    await alice.call_tool("delete_monitor", {"monitor_id": monitor["id"]})
    assert await call(alice, "list_monitors") == []


# Test: errors become clear tool errors.
async def test_errors_become_clear_tool_errors(alice):
    with pytest.raises(ToolError, match="Monitor not found"):
        await alice.call_tool("get_monitor", {"monitor_id": 12345})

    with pytest.raises(ToolError, match="Invalid input"):
        await alice.call_tool("add_monitor", {"name": "x", "url": "not-a-url"})

    with pytest.raises(ToolError):  # interval below the 30 second minimum
        await alice.call_tool("add_monitor", {"name": "x", "url": "https://site.test/", "interval_seconds": 5})


# Test: check now history incidents and report.
async def test_check_now_history_incidents_and_report(alice, monkeypatch):
    # Replaces the real website check with one that always fails with a 503.
    async def failing_check(url, expected_status, timeout_seconds, client=None):
        return CheckOutcome(False, 503, 30, "Expected status 200 but got 503")

    monkeypatch.setattr("app.services.monitoring.perform_http_check", failing_check)
    monkeypatch.setattr("app.services.alerts.send_alert", lambda *args, **kwargs: _noop())
    monkeypatch.setattr("app.services.monitoring.send_alert", lambda *args, **kwargs: _noop())

    monitor = await call(alice, "add_monitor", name="flaky", url="https://site.test/")
    for _ in range(3):  # three failures reach the default threshold
        result = await call(alice, "check_now", monitor_id=monitor["id"])
    assert result["is_up"] is False and result["status_code"] == 503

    assert (await call(alice, "get_monitor", monitor_id=monitor["id"]))["status"] == "down"

    checks = await call(alice, "get_recent_checks", monitor_id=monitor["id"], limit=2)
    assert len(checks) == 2

    incidents = await call(alice, "get_incidents", only_open=True)
    assert len(incidents) == 1 and incidents[0]["monitor_id"] == monitor["id"]

    report = await call(alice, "get_uptime_report", monitor_id=monitor["id"], hours=24)
    assert report["total_checks"] == 3 and report["uptime_percent"] == 0.0 and report["incident_count"] == 1


# A do-nothing replacement for send_alert, so this test sends no alerts.
async def _noop():
    return None


# ----- Isolation between users -----------------------------------------------


# Test: users only see their own monitors through mcp.
async def test_users_only_see_their_own_monitors_through_mcp(running_app, client, auth_headers, other_headers):
    async with mcp_client_for(await make_api_key(client, auth_headers)) as alice_client:
        async with mcp_client_for(await make_api_key(client, other_headers)) as bob_client:
            alices = await call(alice_client, "add_monitor", name="alice's", url="https://site.test/")

            assert await call(bob_client, "list_monitors") == []
            with pytest.raises(ToolError, match="Monitor not found"):
                await bob_client.call_tool("get_monitor", {"monitor_id": alices["id"]})
            with pytest.raises(ToolError, match="Monitor not found"):
                await bob_client.call_tool("delete_monitor", {"monitor_id": alices["id"]})

            # Still there for Alice.
            assert len(await call(alice_client, "list_monitors")) == 1


# Test: monitors made in the rest api show up in mcp.
async def test_monitors_made_in_the_rest_api_show_up_in_mcp(alice, client, auth_headers):
    # Both front doors use the same database and the same services.
    await create_monitor(client, auth_headers, name="made via REST")
    assert [m["name"] for m in await call(alice, "list_monitors")] == ["made via REST"]


# ----- Resource and prompt ---------------------------------------------------


# Test: summary resource.
async def test_summary_resource(alice):
    await call(alice, "add_monitor", name="x", url="https://site.test/")
    contents = await alice.read_resource("uptime://summary")
    import json

    summary = json.loads(contents[0].text)
    assert summary["total_monitors"] == 1 and summary["unknown"] == 1


# Test: investigate prompt mentions the monitor.
async def test_investigate_prompt_mentions_the_monitor(alice):
    prompt = await alice.get_prompt("investigate_incident", {"monitor_id": "7"})
    text = prompt.messages[0].content.text
    assert "monitor 7" in text and "get_recent_checks" in text
