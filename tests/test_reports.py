# =============================================================================
# tests/test_reports.py  -  UPTIME REPORT AND SUMMARY
# =============================================================================
from datetime import timedelta

from app.models import CheckResult, Incident, utcnow
from tests.helpers import create_monitor


# Test: report with no checks has no percentage.
async def test_report_with_no_checks_has_no_percentage(client, auth_headers):
    monitor = await create_monitor(client, auth_headers)
    report = (await client.get(f"/api/v1/monitors/{monitor['id']}/report", headers=auth_headers)).json()
    assert report["total_checks"] == 0
    assert report["uptime_percent"] is None
    assert report["average_response_ms"] is None


# Test: report calculates uptime and average.
async def test_report_calculates_uptime_and_average(client, auth_headers, session):
    monitor = await create_monitor(client, auth_headers)
    now = utcnow()
    # 8 passing checks (100 ms each) and 2 failing ones inside the last 24 hours...
    rows = [CheckResult(monitor_id=monitor["id"], is_up=True, response_time_ms=100, checked_at=now) for _ in range(8)]
    rows += [CheckResult(monitor_id=monitor["id"], is_up=False, checked_at=now) for _ in range(2)]
    # ...and one old failing check that must NOT be counted.
    rows.append(CheckResult(monitor_id=monitor["id"], is_up=False, checked_at=now - timedelta(hours=48)))
    session.add_all(rows)
    session.add(Incident(monitor_id=monitor["id"], started_at=now, reason="test"))
    await session.commit()

    report = (await client.get(f"/api/v1/monitors/{monitor['id']}/report?hours=24", headers=auth_headers)).json()
    assert report["total_checks"] == 10
    assert report["failed_checks"] == 2
    assert report["uptime_percent"] == 80.0
    assert report["average_response_ms"] == 100.0
    assert report["incident_count"] == 1

    # A longer period includes the old failure too.
    longer = (await client.get(f"/api/v1/monitors/{monitor['id']}/report?hours=72", headers=auth_headers)).json()
    assert longer["total_checks"] == 11 and longer["failed_checks"] == 3


# Test: report rejects silly periods.
async def test_report_rejects_silly_periods(client, auth_headers):
    monitor = await create_monitor(client, auth_headers)
    response = await client.get(f"/api/v1/monitors/{monitor['id']}/report?hours=0", headers=auth_headers)
    assert response.status_code == 422


# Test: summary counts each status.
async def test_summary_counts_each_status(client, auth_headers, other_headers, session):
    from app.models import Monitor

    up = await create_monitor(client, auth_headers, name="up")
    down = await create_monitor(client, auth_headers, name="down")
    await create_monitor(client, auth_headers, name="unknown")
    paused = await create_monitor(client, auth_headers, name="paused")
    await create_monitor(client, other_headers, name="someone else's")  # must not be counted

    (await session.get(Monitor, up["id"])).status = "up"
    (await session.get(Monitor, down["id"])).status = "down"
    (await session.get(Monitor, paused["id"])).is_active = False
    session.add(Incident(monitor_id=down["id"], reason="boom"))
    session.add(Incident(monitor_id=up["id"], resolved_at=utcnow()))  # resolved, not "open"
    await session.commit()

    summary = (await client.get("/api/v1/summary", headers=auth_headers)).json()
    assert summary == {
        "total_monitors": 4,
        "up": 1,
        "down": 1,
        "unknown": 1,
        "paused": 1,
        "open_incidents": 1,
    }


# Test: incident endpoints.
async def test_incident_endpoints(client, auth_headers, other_headers, session):
    monitor = await create_monitor(client, auth_headers)
    session.add(Incident(monitor_id=monitor["id"], reason="open one"))
    session.add(Incident(monitor_id=monitor["id"], reason="old one", resolved_at=utcnow()))
    await session.commit()

    everything = (await client.get("/api/v1/incidents", headers=auth_headers)).json()
    only_open = (await client.get("/api/v1/incidents?only_open=true", headers=auth_headers)).json()
    per_monitor = (await client.get(f"/api/v1/monitors/{monitor['id']}/incidents", headers=auth_headers)).json()

    assert len(everything) == 2 and len(per_monitor) == 2
    assert [i["reason"] for i in only_open] == ["open one"]
    assert (await client.get("/api/v1/incidents", headers=other_headers)).json() == []
