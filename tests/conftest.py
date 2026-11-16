# =============================================================================
# tests/conftest.py  -  SHARED SETUP FOR ALL TESTS
# =============================================================================
# pytest automatically loads this file first. Things defined here ("fixtures")
# can be requested by any test just by naming them as a parameter, e.g.
#
#     async def test_something(client, auth_headers): ...
#
# What the tests use:
#   * A throw-away SQLite database file (or the Postgres from TEST_DATABASE_URL).
#     Tables are created before each test and dropped after, so tests never
#     affect each other.
#   * A fake website ("mock site") so no test ever touches the real internet.
#
# Read more: docs/11-testing.md
# =============================================================================

import os
import tempfile

# The settings must be chosen BEFORE the app is imported, because the app
# reads them once when it is imported (see app/config.py).
_temp_folder = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_temp_folder}/test.db"
)
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hmac"
os.environ["ALLOW_PRIVATE_URLS"] = "true"  # tests use fake hosts like http://site.test
os.environ["RUN_BACKGROUND_WORKERS"] = "false"  # tests call the engine directly

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from tests.helpers import AlertCatcher, make_mock_client, register_and_login  # noqa: E402


# Runs around EVERY test: start with empty tables, clean up afterwards.
@pytest_asyncio.fixture(autouse=True)
async def clean_database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield


# A fake web browser that talks directly to our app (no real server, no network).
@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


# A database session for tests that want to look inside the database.
@pytest_asyncio.fixture
async def session():
    async with SessionLocal() as db_session:
        yield db_session


# Headers for a logged-in user "alice".
@pytest_asyncio.fixture
async def auth_headers(client):
    return await register_and_login(client, "alice@example.com")


# Headers for a second logged-in user "bob" (used to test that users are isolated).
@pytest_asyncio.fixture
async def other_headers(client):
    return await register_and_login(client, "bob@example.com")


# A fake website that always answers 200 OK.
@pytest.fixture
def site_up():
    return make_mock_client(lambda request: httpx.Response(200))


# A fake website that always answers 503 (Service Unavailable).
@pytest.fixture
def site_down():
    return make_mock_client(lambda request: httpx.Response(503))


# A fake alert receiver. After a test, `alert_catcher.messages` lists the alerts it received.
@pytest.fixture
def alert_catcher():
    return AlertCatcher()
