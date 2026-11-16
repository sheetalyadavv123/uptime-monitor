# 11. Testing

The project has **91 automated tests**. They run in about 15 seconds and need **no internet** and no setup besides installing the requirements.

```bash
pytest                  # run everything
pytest -x               # stop at the first failure
pytest tests/test_auth.py                      # one file
pytest -k "incident"                           # tests whose name contains "incident"
pytest -v                                      # show every test name
```

## Why tests matter here

- They are **documentation that runs**: a test shows exactly how a feature is supposed to behave.
- They make changes safe: change the code, run the tests, know immediately if you broke something.
- They prove the important promises: users cannot see each other's data, private addresses are blocked, a site is only DOWN after the threshold.

## How the tests are built

```mermaid
flowchart TB
    subgraph Test["One test"]
        T["async def test_...(client, auth_headers)"]
    end
    subgraph Fixtures["conftest.py (shared setup)"]
        F1["clean_database<br/>empty tables before every test"]
        F2["client<br/>fake browser talking to the app in memory"]
        F3["auth_headers / other_headers<br/>logged-in alice and bob"]
        F4["site_up / site_down<br/>fake websites"]
        F5["alert_catcher<br/>fake webhook receiver"]
    end
    T --> F1
    T --> F2
    T --> F3
    T --> F4
    T --> F5
    F2 --> APP["Our real app"]
    APP --> DB[("Throw-away SQLite file<br/>or Postgres via TEST_DATABASE_URL")]
```

**Fixtures** are ready-made helpers. A test asks for one by naming it as a parameter, and pytest prepares it. For example:

```python
async def test_pause_and_resume(client, auth_headers):
    ...
```

`client` and `auth_headers` are created for this test automatically.

## Nothing touches the real internet

```mermaid
flowchart LR
    subgraph Real["Real app"]
        C["perform_http_check()"]
    end
    C -- "normally" --> NET["Real website"]
    C -. "in tests we pass a fake client" .-> MOCK["httpx.MockTransport<br/>answers with the status WE choose"]
```

`make_mock_client(lambda request: httpx.Response(503))` in `tests/helpers.py` builds a fake website that always answers 503. Check functions accept an optional `client` parameter exactly so that tests can pass a fake one.

## The test files

| File | What it proves |
|---|---|
| `test_auth.py` | Register, login, tokens, expired and forged tokens, same error for unknown email and wrong password |
| `test_api_keys.py` | Key shown once, stored hashed, revoked keys stop working, users cannot delete each other's keys |
| `test_monitors_api.py` | CRUD, validation, pagination, pause/resume, cascade delete, per-user limit, user isolation, check-now |
| `test_incident_logic.py` | The DOWN rule (pure function), including a full up→down→up story |
| `test_checks.py` | One HTTP check: OK, wrong status, timeout, connection error |
| `test_monitoring.py` | The engine: incidents opened/closed, one alert per event, claiming, cleanup, and **the real scheduler running in the background** |
| `test_reports.py` | Uptime percentage, averages, time windows, summary counts, incident endpoints |
| `test_url_safety.py` | SSRF protection: blocked addresses, API and checker both refuse them |
| `test_mcp.py` | The MCP server over HTTP with real API keys: auth, all tools, errors, isolation, resource, prompt |
| `test_config.py` | Production safety checks for settings |

## Anatomy of a good test

From `tests/test_monitors_api.py`:

```python
async def test_users_cannot_see_or_change_each_others_monitors(client, auth_headers, other_headers):
    monitor = await create_monitor(client, auth_headers)           # ARRANGE: alice makes a monitor
    url = f"/api/v1/monitors/{monitor['id']}"

    assert (await client.get(url, headers=other_headers)).status_code == 404   # ACT + ASSERT:
    assert (await client.delete(url, headers=other_headers)).status_code == 404  # bob cannot touch it
```

Pattern: **Arrange** (set up) → **Act** (do the thing) → **Assert** (check the result).

## Testing the MCP server

`tests/test_mcp.py` starts the whole app, then connects with a real MCP client over HTTP with a real API key, just like an AI tool. This catches mistakes that unit tests would miss (wrong auth wiring, bad tool schemas).

```mermaid
sequenceDiagram
    participant T as Test
    participant C as FastMCP Client
    participant A as Our app (in memory)
    T->>A: create user + API key (REST)
    T->>C: connect with the key
    C->>A: tools/list, tools/call ...
    A-->>C: results
    T->>T: assert on the results
```

## Run the tests on PostgreSQL

By default tests use a temporary SQLite file. To use PostgreSQL (recommended before a release):

```bash
createdb uptime_test        # or create the database any way you like
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/uptime_test pytest
```

Tables are dropped and recreated for every test, so use a **dedicated test database**.

## The live smoke test

`scripts/smoke_test.py` is not a pytest test. It talks to a **running server** over the network (real scheduler, real HTTP, real MCP) and prints PASS/FAIL lines. See the README for how to run it.

## Writing a new test: a recipe

1. Pick the matching file (or make `tests/test_something.py`).
2. Name it like a sentence: `test_<thing>_<does what>`.
3. Ask for fixtures as parameters (`client`, `auth_headers`...).
4. Arrange, act, assert.
5. Run just that test: `pytest tests/test_x.py::test_name -v`.

## Known setting you may wonder about

`pytest.ini` sets one event loop for the whole run (`asyncio_default_test_loop_scope = session`). The database connection pool lives for the whole process, so it must not be tied to a loop that ends after each test.
