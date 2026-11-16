# =============================================================================
# services/alerts.py  -  TELLING THE USER WHEN A SITE GOES DOWN OR RECOVERS
# =============================================================================
# When the status of a monitor changes, we:
#   1. Write a line to the log (always).
#   2. If the monitor has an `alert_webhook_url`, send a JSON message to it.
#
# A "webhook" is just a web address that receives a message when something
# happens. Slack, Discord, Teams and many other tools give you such addresses,
# so this one feature already connects us to lots of tools.
#
# A failing alert must NEVER break monitoring, so every error is caught and logged.
# =============================================================================

import logging

import httpx

from app.errors import InvalidInputError
from app.models import Monitor, utcnow
from app.services.http_client import create_safe_client
from app.services.incidents import StatusEvent

logger = logging.getLogger(__name__)

ALERT_TIMEOUT_SECONDS = 5


# Builds the JSON message we send. Receivers can rely on this exact shape.
def build_alert_payload(monitor: Monitor, event: StatusEvent, reason: str | None) -> dict:
    return {
        "event": "monitor.down" if event == StatusEvent.WENT_DOWN else "monitor.recovered",
        "monitor": {"id": monitor.id, "name": monitor.name, "url": monitor.url},
        "reason": reason,
        "occurred_at": utcnow().isoformat(),
    }


# Sends the alert. `client` can be passed in by tests so that no real network is used.
async def send_alert(
    monitor: Monitor,
    event: StatusEvent,
    reason: str | None,
    client: httpx.AsyncClient | None = None,
) -> None:
    logger.info("ALERT monitor=%s (%s) event=%s reason=%s", monitor.id, monitor.name, event, reason)

    if not monitor.alert_webhook_url:
        return

    payload = build_alert_payload(monitor, event, reason)
    own_client = client is None
    if own_client:
        client = create_safe_client(ALERT_TIMEOUT_SECONDS)

    try:
        response = await client.post(monitor.alert_webhook_url, json=payload)
        response.raise_for_status()
    except (httpx.HTTPError, InvalidInputError) as error:
        logger.warning("Could not deliver alert for monitor %s: %s", monitor.id, error)
    finally:
        if own_client:
            await client.aclose()
