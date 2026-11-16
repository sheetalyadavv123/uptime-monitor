# =============================================================================
# tests/test_monitors_api.py  -  THE MONITOR REST API
# =============================================================================
from sqlalchemy import func, select

from app.config import settings
from app.models import CheckResult, Monitor
from app.services.checks import CheckOutcome
from tests.helpers import create_monitor


# Test: create monitor uses defaults.
async def test_create_monitor_uses_defaults(client, auth_headers):
    monitor = await create_monitor(client, auth_headers)
    assert monitor["interval_seconds"] == 60
    assert monitor["expected_status"] == 200
    assert monitor["failure_threshold"] == 3
    assert monitor["status"] == "unknown"  # nothing has been checked yet
    assert monitor["is_active"] is True


# Test: create monitor needs login.
async def test_create_monitor_needs_login(client):
    response = await client.post("/api/v1/monitors", json={"name": "x", "url": "https://site.test"})
    assert response.status_code == 401


# Test: create monitor rejects bad input.
async def test_create_monitor_rejects_bad_input(client, auth_headers):
    too_fast = await client.post(
        "/api/v1/monitors",
        json={"name": "x", "url": "https://site.test", "interval_seconds": 5},
        headers=auth_headers,
    )
    not_a_url = await client.post(
        "/api/v1/monitors", json={"name": "x", "url": "hello"}, headers=auth_headers
    )
    ftp_url = await client.post(
        "/api/v1/monitors", json={"name": "x", "url": "ftp://site.test"}, headers=auth_headers
    )
    assert too_fast.status_code == not_a_url.status_code == ftp_url.status_code == 422


# Test: list and get monitors.
async def test_list_and_get_monitors(client, auth_headers):
    first = await create_monitor(client, auth_headers, name="First")
    second = await create_monitor(client, auth_headers, name="Second")

    listed = (await client.get("/api/v1/monitors", headers=auth_headers)).json()
    assert [m["name"] for m in listed] == ["Second", "First"]  # newest first

    one = await client.get(f"/api/v1/monitors/{first['id']}", headers=auth_headers)
    assert one.status_code == 200 and one.json()["name"] == "First"
    assert second["id"] != first["id"]


# Test: pagination.
async def test_pagination(client, auth_headers):
    for number in range(5):
        await create_monitor(client, auth_headers, name=f"Site {number}")

    page = (await client.get("/api/v1/monitors?limit=2&offset=2", headers=auth_headers)).json()
    assert [m["name"] for m in page] == ["Site 2", "Site 1"]

    bad = await client.get("/api/v1/monitors?limit=0", headers=auth_headers)
    assert bad.status_code == 422


# Test: users cannot see or change each others monitors.
async def test_users_cannot_see_or_change_each_others_monitors(client, auth_headers, other_headers):
    monitor = await create_monitor(client, auth_headers)
    url = f"/api/v1/monitors/{monitor['id']}"

    # Bob sees nothing and gets "not found" (we do not reveal that it exists).
    assert (await client.get("/api/v1/monitors", headers=other_headers)).json() == []
    assert (await client.get(url, headers=other_headers)).status_code == 404
    assert (await client.patch(url, json={"name": "hacked"}, headers=other_headers)).status_code == 404
    assert (await client.delete(url, headers=other_headers)).status_code == 404
    assert (await client.post(url + "/check-now", headers=other_headers)).status_code == 404
    assert (await client.get(url + "/checks", headers=other_headers)).status_code == 404
    assert (await client.get(url + "/report", headers=other_headers)).status_code == 404

    # And Alice's monitor is untouched.
    assert (await client.get(url, headers=auth_headers)).json()["name"] == "Test site"


# Test: update only changes sent fields.
async def test_update_only_changes_sent_fields(client, auth_headers):
    monitor = await create_monitor(client, auth_headers, interval_seconds=120)
    response = await client.patch(
        f"/api/v1/monitors/{monitor['id']}", json={"name": "Renamed"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["interval_seconds"] == 120  # unchanged


# Test: pause and resume.
async def test_pause_and_resume(client, auth_headers, session):
    monitor = await create_monitor(client, auth_headers)
    url = f"/api/v1/monitors/{monitor['id']}"

    paused = await client.patch(url, json={"is_active": False}, headers=auth_headers)
    assert paused.json()["is_active"] is False

    resumed = await client.patch(url, json={"is_active": True}, headers=auth_headers)
    assert resumed.json()["is_active"] is True


# Test: webhook can be added and removed.
async def test_webhook_can_be_added_and_removed(client, auth_headers):
    monitor = await create_monitor(client, auth_headers)
    url = f"/api/v1/monitors/{monitor['id']}"

    added = await client.patch(url, json={"alert_webhook_url": "https://hooks.test/x"}, headers=auth_headers)
    assert added.json()["alert_webhook_url"] == "https://hooks.test/x"

    removed = await client.patch(url, json={"alert_webhook_url": None}, headers=auth_headers)
    assert removed.json()["alert_webhook_url"] is None


# Test: delete removes monitor and its history.
async def test_delete_removes_monitor_and_its_history(client, auth_headers, session):
    monitor = await create_monitor(client, auth_headers)
    session.add(CheckResult(monitor_id=monitor["id"], is_up=True, status_code=200, response_time_ms=10))
    await session.commit()

    deleted = await client.delete(f"/api/v1/monitors/{monitor['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/monitors/{monitor['id']}", headers=auth_headers)).status_code == 404

    # The database removed the check results too (ON DELETE CASCADE).
    remaining = await session.scalar(select(func.count()).select_from(CheckResult))
    assert remaining == 0


# Test: monitor limit per user.
async def test_monitor_limit_per_user(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "max_monitors_per_user", 2)
    await create_monitor(client, auth_headers)
    await create_monitor(client, auth_headers)

    response = await client.post(
        "/api/v1/monitors", json={"name": "third", "url": "https://site.test"}, headers=auth_headers
    )
    assert response.status_code == 403


# Test: new monitor is due immediately.
async def test_new_monitor_is_due_immediately(client, auth_headers, session):
    from app.models import utcnow

    monitor = await create_monitor(client, auth_headers)
    stored = await session.get(Monitor, monitor["id"])
    assert stored.next_check_at <= utcnow()


# Test: check now runs a check and updates the monitor.
async def test_check_now_runs_a_check_and_updates_the_monitor(client, auth_headers, monkeypatch):
    # Replaces the real website check with one that instantly says "up, 42 ms".
    async def fake_check(url, expected_status, timeout_seconds, client=None):
        return CheckOutcome(True, 200, 42, None)

    monkeypatch.setattr("app.services.monitoring.perform_http_check", fake_check)
    monitor = await create_monitor(client, auth_headers)

    result = await client.post(f"/api/v1/monitors/{monitor['id']}/check-now", headers=auth_headers)
    assert result.status_code == 200
    assert result.json()["is_up"] is True and result.json()["response_time_ms"] == 42

    updated = (await client.get(f"/api/v1/monitors/{monitor['id']}", headers=auth_headers)).json()
    assert updated["status"] == "up"
    assert updated["last_checked_at"] is not None

    history = (await client.get(f"/api/v1/monitors/{monitor['id']}/checks", headers=auth_headers)).json()
    assert len(history) == 1


# Test: unknown monitor id is 404.
async def test_unknown_monitor_id_is_404(client, auth_headers):
    assert (await client.get("/api/v1/monitors/9999", headers=auth_headers)).status_code == 404
    assert (await client.get("/api/v1/monitors/abc", headers=auth_headers)).status_code == 422


# Test: health endpoints need no login.
async def test_health_endpoints_need_no_login(client):
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/health/ready")).json() == {"status": "ok"}


# Test: root page points to the docs.
async def test_root_page_points_to_the_docs(client):
    body = (await client.get("/")).json()
    assert body["docs"] == "/docs" and body["mcp"] == "/mcp"
