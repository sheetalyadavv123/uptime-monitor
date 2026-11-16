# 13. Glossary and exercises

## Glossary

| Term | Plain meaning |
|---|---|
| **API** | A set of URLs another program can call to get things done |
| **REST** | A common style of API: URLs name things (`/monitors/5`), HTTP methods say what to do (GET, POST...) |
| **Endpoint / route** | One URL + method that the API answers, e.g. `GET /api/v1/monitors` |
| **JSON** | Text format for data: `{"name": "Example", "interval_seconds": 60}` |
| **HTTP status code** | A number saying how a request went: 200 OK, 404 not found, 500 server error |
| **FastAPI** | The Python library that builds our REST API |
| **FastMCP** | The Python library that builds our MCP server |
| **MCP** | Model Context Protocol: a standard for AI assistants to use outside tools |
| **MCP tool** | An action the AI may run (like `add_monitor`) |
| **MCP resource** | Read-only data an AI app can attach (like `uptime://summary`) |
| **MCP prompt** | A ready-made instruction template the user can pick |
| **Decorator** | The `@something` line above a function that registers or changes it (`@router.get`, `@mcp.tool`) |
| **Pydantic** | The library that validates data and describes its shape |
| **Schema** | A Pydantic class describing JSON (`MonitorCreate`) |
| **Model** | A SQLAlchemy class describing a database table (`Monitor`) |
| **ORM** | Lets you work with tables as Python classes (SQLAlchemy is our ORM) |
| **SQLAlchemy** | The library that talks to the database |
| **Session** | One conversation with the database; `commit()` saves its changes together |
| **Transaction** | A group of database changes that succeed or fail as one |
| **Migration** | A small script that changes the database structure from one version to the next |
| **Alembic** | The tool that creates and runs migrations |
| **Index** | A lookup structure that makes queries fast |
| **Foreign key** | A column pointing to a row in another table |
| **Cascade delete** | Deleting a parent row automatically deletes its children |
| **Dependency (FastAPI)** | Something a route asks for in its parameters (`SessionDep`, `CurrentUser`) |
| **Dependency injection** | FastAPI preparing those things and passing them in for you |
| **Router** | A group of routes in one file |
| **Middleware** | Code that wraps every request or call |
| **Lifespan** | Code that runs once at startup and once at shutdown |
| **Async / await** | A way to write code that can wait (for the network or database) without blocking everything else |
| **Event loop** | The thing that runs async code and switches between waiting tasks |
| **asyncio task** | A background job inside the event loop |
| **Queue** | A line of jobs waiting for a worker |
| **Worker** | A task that takes jobs from the queue and does them |
| **Scheduler** | The loop that decides what is due and queues it |
| **Hash** | A one-way scramble of data. Cannot be reversed |
| **Argon2** | A slow, secure password-hashing algorithm |
| **JWT** | A signed token that says "this is user 7 until time X" |
| **Bearer token** | A token sent in the header `Authorization: Bearer <token>` |
| **API key** | A long random secret used instead of a password by programs |
| **Authentication** | Proving who you are |
| **Authorization** | Deciding what you may do |
| **SSRF** | Tricking a server into making requests to places the attacker cannot reach |
| **Webhook** | A URL that receives a message when something happens |
| **Redirect** | A website answering "go to this other address" (status 301 / 302) |
| **Uptime %** | Passed checks divided by all checks, times 100 |
| **Incident** | One outage: from DOWN until recovery |
| **Threshold** | How many failures in a row before we call it DOWN |
| **Liveness / readiness** | "Is the process running?" / "Can it do its job (database reachable)?" |
| **Environment variable** | A setting passed from outside the code, e.g. `DATABASE_URL` |
| **Docker image / container** | A packaged app / a running copy of it |
| **Fixture (pytest)** | A ready-made helper that tests can ask for |
| **Mock** | A fake replacement (like a fake website) used in tests |
| **Pure function** | A function that only depends on its inputs and changes nothing outside (`decide_next_state`) |
| **UTC** | The world time standard we use everywhere inside the app |

## Exercises

Do them in order: each one builds a skill. After each exercise run `pytest` to check nothing broke. A hint says where to start; try without the hint first.

### Level 1: read and observe

1. **Follow a request.** Start the app, create a monitor on `/docs`, and read the log lines. Open `routers/monitors.py`, `services/monitors.py` and `models.py` and find every line that ran. *(Doc 2 and doc 4 help.)*
2. **Break the rule on purpose.** In `tests/test_incident_logic.py`, change one expected value so a test fails. Read the failure message. Undo it.
3. **Explore the live docs.** On `/docs`, call `GET /api/v1/summary` before and after pausing a monitor. What changes?

### Level 2: small changes

4. **Change a default.** Make the default `interval_seconds` 120 instead of 60. *(Hint: `schemas.py` and `models.py`; update the test that checks defaults.)*
5. **Add a field.** Add a `description` text field to monitors (optional, up to 500 characters). It touches four places: `models.py`, a **new migration**, `schemas.py` (create, update, read) and `services/monitors.py`. Add a test. *(Doc 5.)*
6. **Add a filter.** Let `GET /api/v1/monitors?status=down` return only DOWN monitors. *(Hint: add a parameter in the router, pass it to `list_monitors`, add a `.where(...)` in the service.)*

### Level 3: new features

7. **Slack-friendly alerts.** If the webhook URL contains `hooks.slack.com`, send `{"text": "🔴 My website is DOWN: <reason>"}` instead of the generic JSON. *(Hint: `build_alert_payload` in `alerts.py`. Test with `alert_catcher`.)*
8. **Sign the webhook.** Add an `X-Signature` header with an HMAC-SHA256 of the body using a per-monitor secret, so receivers can verify messages are genuine. *(Hint: `hmac` and `hashlib` from the standard library.)*
9. **A new MCP tool.** Add `list_down_monitors` ([doc 9](09-mcp-server.md)) and a test.
10. **Check body content.** Add an optional `expected_text` to monitors: the check passes only if the response body contains it. *(Hint: you must now read the body, so `perform_http_check` must stop streaming only the headers, and read a limited number of bytes.)*

### Level 4: design challenges

11. **Retry once before failing.** Make a failed check retry after 2 seconds before counting as a failure. Where should this live: `checks.py` or `monitoring.py`? Why?
12. **Maintenance windows.** Let a user pause alerts (not checks) for a time range. Which tables, services and tools change?
13. **Move the queue to Redis.** Keep `claim_due_monitors` and `run_check`, replace the in-memory queue and run workers as a separate process. What do you gain, and what gets harder? *(Doc 7, "Scaling further".)*
14. **Read-only API keys.** Add a `read_only` flag to API keys, and make the MCP tools that change data refuse such keys. *(Hint: put the flag into `AccessToken.claims` in `ApiKeyVerifier`.)*

## Quiz yourself

1. Why do we return 404 (not 403) when someone asks for another user's monitor?
2. What is the difference between `models.py` and `schemas.py`?
3. Why is `next_check_at` moved *before* the website is checked?
4. Why do services raise `AppError` instead of `HTTPException`?
5. Why is the API key shown only once?
6. What would happen if `run_check` sent the alert *before* committing?
7. Why can't an MCP client use a login token?
8. What does `FOR UPDATE SKIP LOCKED` protect us from?

<details>
<summary>Answers</summary>

1. So nobody can find out which ids exist.
2. Models are database tables; schemas are the JSON shapes of the API. Keeping them apart avoids leaking columns like `hashed_password`.
3. So the monitor is not queued again while a worker is still busy with it, and so two app copies do not check it twice.
4. Because the same services are used by the REST API (needs status codes) and by MCP (needs tool errors). Each front door translates the neutral error.
5. We only store its hash, so we cannot show it again. If the database leaks, the keys are still safe.
6. A slow or failing webhook could delay or break the commit, and we could lose the result or send alerts for changes that were never saved.
7. Different mechanisms on purpose: the MCP server only accepts API keys, which are long-lived and revocable separately from login sessions.
8. Two app copies claiming (and then checking) the same monitor at the same time.
</details>
