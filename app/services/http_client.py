# =============================================================================
# http_client.py  -  THE HTTP CLIENT WE USE FOR EVERY OUTGOING REQUEST
# =============================================================================
# Both the website checker and the webhook alerts send requests to addresses
# chosen by users. So both use the "safe" client created here.
#
# What makes it safe:
#   - It checks every request address with ensure_public_url() BEFORE sending.
#     "Every request" includes each redirect step, so a public site cannot
#     redirect us to a private address.
#   - It follows at most 5 redirects.
#   - It has a timeout, so a slow website cannot block us forever.
# =============================================================================

import httpx

from app.services.url_safety import ensure_public_url


# An "event hook": httpx calls this function just before sending each request.
# If it raises an error, the request is never sent.
async def _check_request_is_public(request: httpx.Request) -> None:
    await ensure_public_url(str(request.url))


# Builds the client. The caller must close it (we use `async with` for that).
def create_safe_client(timeout_seconds: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
        max_redirects=5,
        event_hooks={"request": [_check_request_is_public]},
        headers={"User-Agent": "UptimeMonitor/1.0"},
    )
