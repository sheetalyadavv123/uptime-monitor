# =============================================================================
# scripts/smoke_test.py  -  A LIVE END-TO-END DEMO AGAINST A RUNNING SERVER
# =============================================================================
# The automated tests (tests/) run everything inside Python. This script is
# different: it talks to a REAL running server over the network, exactly like
# a real user and a real AI tool would. It is also a nice way to SEE the app
# work from start to finish.
#
# HOW TO RUN IT
#   1. Start the app with private addresses allowed (this script uses a fake
#      website on localhost, which is normally blocked for safety):
#
#         ALLOW_PRIVATE_URLS=true uvicorn app.main:app
#
#   2. In a second terminal:
#
#         python scripts/smoke_test.py
#
# WHAT IT DOES
#   - Starts a fake website and a fake alert receiver on your computer.
#   - Registers a user, logs in, creates a monitor through the REST API.
#   - Waits for the background scheduler to run the first check by itself.
#   - Makes the fake website fail  -> expects DOWN + an incident + an alert.
#   - Makes the fake website work  -> expects UP again + a recovery alert.
#   - Creates an API key and talks to the MCP server like an AI tool would.
# =============================================================================

import asyncio
import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SITE_PORT = 9101  # our fake website
ALERT_PORT = 9102  # our fake alert receiver

# What the fake website answers. We change this during the demo.
site_status = {"code": 200}
# Every alert the fake receiver gets.
received_alerts: list[dict] = []


# The fake website: always answers with whatever status code we set above.
class FakeSite(BaseHTTPRequestHandler):
    # Answers every GET request with the current status code.
    def do_GET(self):
        self.send_response(site_status["code"])
        self.end_headers()

    # Silences the default request logging.
    def log_message(self, *args):
        pass  # keep the output quiet


# The fake alert receiver: remembers every JSON message it receives.
class FakeAlertReceiver(BaseHTTPRequestHandler):
    # Reads the JSON body of the POST request and remembers it.
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        received_alerts.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.end_headers()

    # Silences the default request logging.
    def log_message(self, *args):
        pass


# Starts a small web server in a background thread.
def start_server(handler, port: int) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# Prints a result line and stops the script if the check failed.
def check(description: str, condition: bool) -> None:
    print(("  PASS  " if condition else "  FAIL  ") + description)
    if not condition:
        sys.exit(1)


# Waits (up to `seconds`) until `condition()` becomes true.
def wait_for(condition, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.3)
    return False


def run_rest_part() -> str:
    """Runs the REST API part of the demo. Returns the monitor id."""
    http = httpx.Client(base_url=BASE_URL, timeout=15)

    print("\n1. REST API: register, log in, create a monitor")
    email = f"demo-{uuid.uuid4().hex[:8]}@example.com"
    http.post("/api/v1/auth/register", json={"email": email, "password": "demo-password-123"})
    token = http.post(
        "/api/v1/auth/login", data={"username": email, "password": "demo-password-123"}
    ).json()["access_token"]
    http.headers["Authorization"] = f"Bearer {token}"

    monitor = http.post(
        "/api/v1/monitors",
        json={
            "name": "Fake site",
            "url": f"http://127.0.0.1:{SITE_PORT}/",
            "interval_seconds": 30,
            "failure_threshold": 1,  # go DOWN after one failed check (faster demo)
            "alert_webhook_url": f"http://127.0.0.1:{ALERT_PORT}/alert",
        },
    ).json()
    monitor_url = f"/api/v1/monitors/{monitor['id']}"
    check("monitor created", monitor["status"] == "unknown")

    print("\n2. Background scheduler: the first check happens by itself")
    went_up = wait_for(lambda: http.get(monitor_url).json()["status"] == "up", 20)
    check("scheduler checked the site and it is UP", went_up)

    print("\n3. The website breaks: expect DOWN, an incident and an alert")
    site_status["code"] = 500
    http.post(monitor_url + "/check-now")
    check("monitor is DOWN", http.get(monitor_url).json()["status"] == "down")
    check("one open incident", len(http.get("/api/v1/incidents?only_open=true").json()) == 1)
    check("alert received: monitor.down", wait_for(lambda: any(a["event"] == "monitor.down" for a in received_alerts), 5))

    print("\n4. The website is fixed: expect UP, a closed incident and a recovery alert")
    site_status["code"] = 200
    http.post(monitor_url + "/check-now")
    check("monitor is UP again", http.get(monitor_url).json()["status"] == "up")
    check("no open incidents", http.get("/api/v1/incidents?only_open=true").json() == [])
    check("alert received: monitor.recovered", wait_for(lambda: any(a["event"] == "monitor.recovered" for a in received_alerts), 5))

    report = http.get(monitor_url + "/report").json()
    print(f"     report: {report['total_checks']} checks, {report['uptime_percent']}% uptime")

    print("\n5. Create an API key for the MCP server")
    api_key = http.post("/api/v1/api-keys", json={"name": "smoke test"}).json()["key"]
    check("API key created", api_key.startswith("upm_"))
    return api_key, monitor["id"]


async def run_mcp_part(api_key: str, monitor_id: int) -> None:
    """Runs the MCP part of the demo, acting like an AI tool."""
    print("\n6. MCP server: connect like an AI tool would")
    transport = StreamableHttpTransport(f"{BASE_URL}/mcp", auth=api_key)
    async with Client(transport) as mcp_client:
        tools = [tool.name for tool in await mcp_client.list_tools()]
        check(f"found {len(tools)} tools", "add_monitor" in tools and "get_uptime_report" in tools)

        result = await mcp_client.call_tool("list_monitors", {})
        monitors = result.structured_content["result"]
        check("list_monitors returns our monitor", [m["id"] for m in monitors] == [monitor_id])

        report = (await mcp_client.call_tool("get_uptime_report", {"monitor_id": monitor_id})).structured_content
        check("get_uptime_report works", report["total_checks"] >= 3)

        incidents = (await mcp_client.call_tool("get_incidents", {"monitor_id": monitor_id})).structured_content["result"]
        check("get_incidents shows the finished outage", len(incidents) == 1 and incidents[0]["resolved_at"])

    print("\n7. MCP server rejects a wrong key")
    bad_transport = StreamableHttpTransport(f"{BASE_URL}/mcp", auth="upm_wrong")
    try:
        async with Client(bad_transport) as bad_client:
            await bad_client.list_tools()
        check("wrong key rejected", False)
    except Exception:
        check("wrong key rejected", True)


# Runs the whole demo: start the fake servers, run the REST part, then the MCP part.
def main() -> None:
    start_server(FakeSite, SITE_PORT)
    start_server(FakeAlertReceiver, ALERT_PORT)
    print(f"Testing the server at {BASE_URL}")
    api_key, monitor_id = run_rest_part()
    asyncio.run(run_mcp_part(api_key, monitor_id))
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
