# =============================================================================
# services/checks.py  -  CHECKING ONE WEBSITE
# =============================================================================
# This file does ONE job: send a request to a URL and describe what happened.
# It does not touch the database. (Saving the result is done in monitoring.py.)
#
# A check is "up" when the website answers with the status code we expect
# (200 by default) before the timeout. Everything else is "down":
# wrong status code, timeout, DNS failure, connection refused, bad certificate...
# =============================================================================

import time
from dataclasses import dataclass

import httpx

from app.errors import InvalidInputError
from app.services.http_client import create_safe_client


# The result of one check, as plain data.
@dataclass
class CheckOutcome:
    is_up: bool
    status_code: int | None  # None when we got no answer at all
    response_time_ms: int | None
    error: str | None  # a human-readable reason when is_up is False


# Requests the URL once and returns a CheckOutcome. It never raises for normal
# failures: a failure is a valid result ("the site is down"), not a crash.
# `client` can be passed in by tests so that no real network is used.
async def perform_http_check(
    url: str,
    expected_status: int,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
) -> CheckOutcome:
    own_client = client is None
    if own_client:
        client = create_safe_client(timeout_seconds)

    started = time.perf_counter()
    try:
        # `stream` returns as soon as the headers arrive, without downloading
        # the whole page. We only care about the status code, and this stops a
        # huge page from wasting our bandwidth and memory.
        async with client.stream("GET", url) as response:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code == expected_status:
                return CheckOutcome(True, response.status_code, elapsed_ms, None)
            return CheckOutcome(
                False,
                response.status_code,
                elapsed_ms,
                f"Expected status {expected_status} but got {response.status_code}",
            )
    except httpx.TimeoutException:
        return CheckOutcome(False, None, None, f"Timed out after {timeout_seconds} seconds")
    except (httpx.HTTPError, httpx.InvalidURL, InvalidInputError) as error:
        # Examples: connection refused, DNS failure, SSL error, blocked private address.
        message = f"{type(error).__name__}: {error}"
        return CheckOutcome(False, None, None, message[:500])
    finally:
        if own_client:
            await client.aclose()
