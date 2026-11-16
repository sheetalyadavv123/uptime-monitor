# =============================================================================
# tests/test_checks.py  -  CHECKING ONE WEBSITE
# =============================================================================
# We never contact the real internet. `make_mock_client` creates a fake website
# whose answer we control.
# =============================================================================
import httpx

from tests.helpers import make_mock_client
from app.services.checks import perform_http_check


# Test: status 200 is up.
async def test_status_200_is_up():
    client = make_mock_client(lambda request: httpx.Response(200))
    outcome = await perform_http_check("https://site.test/", 200, 5, client=client)
    assert outcome.is_up is True
    assert outcome.status_code == 200
    assert outcome.response_time_ms is not None
    assert outcome.error is None


# Test: unexpected status is down with a clear reason.
async def test_unexpected_status_is_down_with_a_clear_reason():
    client = make_mock_client(lambda request: httpx.Response(503))
    outcome = await perform_http_check("https://site.test/", 200, 5, client=client)
    assert outcome.is_up is False
    assert outcome.status_code == 503
    assert "Expected status 200 but got 503" in outcome.error


# Test: a different expected status can be up.
async def test_a_different_expected_status_can_be_up():
    client = make_mock_client(lambda request: httpx.Response(404))
    outcome = await perform_http_check("https://site.test/", 404, 5, client=client)
    assert outcome.is_up is True


# Test: timeout is down.
async def test_timeout_is_down():
    # A fake website that never answers in time.
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    outcome = await perform_http_check("https://site.test/", 200, 5, client=make_mock_client(handler))
    assert outcome.is_up is False
    assert outcome.status_code is None
    assert "Timed out" in outcome.error


# Test: connection error is down.
async def test_connection_error_is_down():
    # A fake website that refuses the connection.
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    outcome = await perform_http_check("https://site.test/", 200, 5, client=make_mock_client(handler))
    assert outcome.is_up is False
    assert "ConnectError" in outcome.error
