# =============================================================================
# tests/test_monitoring.py  -  THE MONITORING ENGINE (checks, incidents, alerts)
# =============================================================================
# These tests run the real engine code against the test database, with fake
# websites and a fake alert receiver. Nothing touches the internet.
# =============================================================================
import asyncio
from datetime import timedelta

import httpx
from sqlalchemy import select

from app.config import settings
from app.models import CheckResult, Incident, Monitor, User, utcnow
from app.services.checks import CheckOutcome
from app.services.monitoring import (
    check_monitor_by_id,
    claim_due_monitors,
    delete_old_results,
    run_check,
)
from app.workers.scheduler import Scheduler
from tests.helpers import make_mock_client


# Creates a user and a monitor directly in the database.
async def make_monitor(session, **fields) -> Monitor:
    user = User(email=f"user{utcnow().timestamp()}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    monitor = Monitor(
        user_id=user.id,
        name="Test",
        url="https://site.test/",
        alert_webhook_url="https://hooks.test/alert",
        failure_threshold=3,
        **fields,
    )
    session.add(monitor)
    await session.commit()
    return monitor


# Test: failures open an incident and send one alert.
async def test_failures_open_an_incident_and_send_one_alert(session, site_down, alert_catcher):
    monitor = await make_monitor(session)

    for _ in range(4):  # four failing checks, threshold is 3
        await run_check(session, monitor, check_client=site_down, alert_client=alert_catcher.client)

    assert monitor.status == "down"
    incidents = list(await session.scalars(select(Incident)))
    assert len(incidents) == 1  # ONE incident, not one per failed check
    assert incidents[0].resolved_at is None
    assert "got 503" in incidents[0].reason

    assert len(alert_catcher.messages) == 1  # ONE alert, sent when it went down
    assert alert_catcher.messages[0]["event"] == "monitor.down"
    assert alert_catcher.messages[0]["monitor"]["name"] == "Test"


# Test: recovery closes the incident and sends an alert.
async def test_recovery_closes_the_incident_and_sends_an_alert(
    session, site_down, site_up, alert_catcher
):
    monitor = await make_monitor(session)
    for _ in range(3):
        await run_check(session, monitor, check_client=site_down, alert_client=alert_catcher.client)

    await run_check(session, monitor, check_client=site_up, alert_client=alert_catcher.client)

    assert monitor.status == "up"
    assert monitor.consecutive_failures == 0
    incident = await session.scalar(select(Incident))
    await session.refresh(incident)
    assert incident.resolved_at is not None
    assert [m["event"] for m in alert_catcher.messages] == ["monitor.down", "monitor.recovered"]


# Test: a single failure does not create an incident.
async def test_a_single_failure_does_not_create_an_incident(session, site_down, site_up):
    monitor = await make_monitor(session)
    await run_check(session, monitor, check_client=site_up)
    await run_check(session, monitor, check_client=site_down)
    await run_check(session, monitor, check_client=site_up)

    assert monitor.status == "up"
    assert await session.scalar(select(Incident)) is None


# Test: every check is saved.
async def test_every_check_is_saved(session, site_up, site_down):
    monitor = await make_monitor(session)
    await run_check(session, monitor, check_client=site_up)
    await run_check(session, monitor, check_client=site_down)

    results = list(await session.scalars(select(CheckResult).order_by(CheckResult.id)))
    assert [r.is_up for r in results] == [True, False]
    assert results[0].status_code == 200 and results[1].status_code == 503


# Test: monitor without webhook sends no alert.
async def test_monitor_without_webhook_sends_no_alert(session, site_down, alert_catcher):
    monitor = await make_monitor(session)
    monitor.alert_webhook_url = None
    for _ in range(3):
        await run_check(session, monitor, check_client=site_down, alert_client=alert_catcher.client)
    assert alert_catcher.messages == []
    assert monitor.status == "down"  # it still goes down, we just do not notify


# Test: a broken webhook never breaks monitoring.
async def test_a_broken_webhook_never_breaks_monitoring(session, site_down):
    broken_webhook = make_mock_client(lambda request: httpx.Response(500))
    monitor = await make_monitor(session)

    for _ in range(3):
        await run_check(session, monitor, check_client=site_down, alert_client=broken_webhook)

    assert monitor.status == "down"  # the check result was still saved


# Test: claim due monitors only returns due active monitors.
async def test_claim_due_monitors_only_returns_due_active_monitors(session):
    now = utcnow()
    due = await make_monitor(session, next_check_at=now - timedelta(seconds=1), interval_seconds=60)
    await make_monitor(session, next_check_at=now + timedelta(hours=1))  # not due yet
    await make_monitor(session, next_check_at=now - timedelta(seconds=1), is_active=False)  # paused

    claimed = await claim_due_monitors(session)
    assert claimed == [due.id]


# Test: a claimed monitor is not claimed twice.
async def test_a_claimed_monitor_is_not_claimed_twice(session):
    monitor = await make_monitor(
        session, next_check_at=utcnow() - timedelta(seconds=1), interval_seconds=60
    )

    first = await claim_due_monitors(session)
    second = await claim_due_monitors(session)

    assert first == [monitor.id]
    assert second == []  # its next_check_at was moved one interval into the future
    await session.refresh(monitor)
    assert monitor.next_check_at > utcnow() + timedelta(seconds=50)


# Test: check by id skips paused monitors.
async def test_check_by_id_skips_paused_monitors(session, monkeypatch):
    calls = []

    # A fake check that records that it was called.
    async def fake_check(*args, **kwargs):
        calls.append(1)
        return CheckOutcome(True, 200, 5, None)

    monkeypatch.setattr("app.services.monitoring.perform_http_check", fake_check)
    monitor = await make_monitor(session, is_active=False)

    await check_monitor_by_id(monitor.id)
    await check_monitor_by_id(99999)  # a monitor that does not exist
    assert calls == []


# Test: old results are deleted and recent ones kept.
async def test_old_results_are_deleted_and_recent_ones_kept(session):
    monitor = await make_monitor(session)
    old = utcnow() - timedelta(days=settings.check_retention_days + 1)
    session.add_all(
        [
            CheckResult(monitor_id=monitor.id, is_up=True, checked_at=old),
            CheckResult(monitor_id=monitor.id, is_up=True, checked_at=utcnow()),
        ]
    )
    await session.commit()

    deleted = await delete_old_results(session)
    assert deleted == 1
    assert len(list(await session.scalars(select(CheckResult)))) == 1


# Test: scheduler checks due monitors in the background.
async def test_scheduler_checks_due_monitors_in_the_background(session, monkeypatch):
    # The whole engine together: scheduler loop -> queue -> worker -> database.
    # Replaces the real website check with one that instantly says "up".
    async def fake_check(url, expected_status, timeout_seconds, client=None):
        return CheckOutcome(True, 200, 7, None)

    monkeypatch.setattr("app.services.monitoring.perform_http_check", fake_check)
    monkeypatch.setattr(settings, "scheduler_interval_seconds", 0.1)
    monkeypatch.setattr(settings, "worker_count", 2)
    monitor = await make_monitor(session, next_check_at=utcnow() - timedelta(seconds=1))
    monitor_id = monitor.id  # remember it: after expire_all() we may not read attributes

    scheduler = Scheduler()
    await scheduler.start()
    try:
        # Wait (at most 5 seconds) until the first result shows up.
        for _ in range(50):
            await asyncio.sleep(0.1)
            session.expire_all()
            if await session.scalar(select(CheckResult).where(CheckResult.monitor_id == monitor_id)):
                break
    finally:
        await scheduler.stop()

    results = list(await session.scalars(select(CheckResult).where(CheckResult.monitor_id == monitor_id)))
    assert len(results) == 1  # checked once, and NOT again (its interval is 60 seconds)
    await session.refresh(monitor)
    assert monitor.status == "up"
