# Uptime Monitor

A backend service that **watches websites and tells you when they go down**.
It has two "front doors" on top of the same logic:

- a **REST API** (built with **FastAPI**) for apps and scripts
- an **MCP server** (built with **FastMCP**) so an AI assistant like Claude can use it in a chat:
  *"what went down last night?"*, *"start watching my portfolio site"*

Everything in this project is written to be **read and understood**, even if you have never used FastAPI or FastMCP.
Every file starts with a comment that explains what the file is for, and every function has a plain-language comment above it.

```mermaid
flowchart LR
    U["You / your app<br/>(REST API)"] --> API
    AI["AI assistant<br/>(MCP)"] --> MCP
    subgraph App["This project (one app)"]
        API["FastAPI routes<br/>/api/v1/..."] --> S["Services<br/>(the real logic)"]
        MCP["FastMCP tools<br/>/mcp"] --> S
        W["Background workers<br/>(check websites)"] --> S
    end
    S --> DB[("Database<br/>PostgreSQL / SQLite")]
    W --> WEB["The websites<br/>being watched"]
    W --> HOOK["Your alert webhook"]
```

---

## What it can do

| Feature | Details |
|---|---|
| Accounts | Register, log in (JWT tokens), passwords stored as Argon2 hashes |
| Monitors | Add a URL, choose how often to check (30 s to 1 day), pause / resume / delete |
| Automatic checks | Background scheduler and workers check every monitor on time |
| Smart "down" detection | A site is only DOWN after several failed checks in a row (no false alarms) |
| Incidents | Every outage is recorded with a start time, end time and reason |
| Alerts | Sends a JSON message to your webhook when a site goes down or recovers |
| Reports | Uptime percentage, average response time, incident count for any period |
| MCP server | 10 tools, 1 resource and 1 prompt for AI assistants, protected by API keys |
| Safety | Blocks attempts to make the server probe private networks (SSRF), per-user data isolation |
| Production-ready | Migrations (Alembic), Docker, health checks, 91 automated tests |

---

## Quick start (about 3 minutes, nothing to install except Python)

You need **Python 3.13** (3.12 should also work). The commands below use a local SQLite file as the database, so you do not need to install a database.

```bash
# 1. Create an isolated Python environment and activate it
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install the libraries
pip install -r requirements-dev.txt

# 3. Create your settings file (the defaults are fine for local use)
cp .env.example .env               # Windows: copy .env.example .env

# 4. Create the database tables
alembic upgrade head

# 5. Start the app (--reload restarts it when you edit a file)
uvicorn app.main:app --reload
```

Now open **http://localhost:8000/docs**. This page is generated automatically by FastAPI and lets you try every endpoint in your browser.

### Try it in the browser (the /docs page)

1. Open `POST /api/v1/auth/register` → **Try it out** → enter an email and a password (8+ characters) → **Execute**.
2. Click the green **Authorize** button at the top → enter your email as *username* and your password → **Authorize**.
3. Open `POST /api/v1/monitors` → **Try it out** → use `{"name": "Example", "url": "https://example.com"}` → **Execute**.
4. Wait about 10 seconds, then `GET /api/v1/monitors`. The `status` is now `up` and `last_checked_at` is filled in.
5. Try `GET /api/v1/monitors/{monitor_id}/checks` and `GET /api/v1/monitors/{monitor_id}/report`.

> The app refuses to monitor private addresses like `http://localhost:3000` (a safety feature, see [docs/10-security.md](docs/10-security.md)).
> To monitor something on your own computer while learning, start the app with `ALLOW_PRIVATE_URLS=true uvicorn app.main:app --reload`.

### Try it from the terminal

```bash
curl -X POST localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
     -d '{"email": "me@example.com", "password": "my-password-123"}'

curl -X POST localhost:8000/api/v1/auth/login \
     -d "username=me@example.com&password=my-password-123"
# -> {"access_token": "eyJ...", "token_type": "bearer"}

curl -X POST localhost:8000/api/v1/monitors -H "Authorization: Bearer eyJ..." \
     -H "Content-Type: application/json" -d '{"name": "Example", "url": "https://example.com"}'
```

### Run the whole thing automatically (live demo script)

This starts a fake website and a fake alert receiver, breaks the website on purpose, and checks that the app detects the outage, records an incident, sends alerts, and that the MCP server works.

```bash
# terminal 1
ALLOW_PRIVATE_URLS=true uvicorn app.main:app
# terminal 2
python scripts/smoke_test.py
```

---

## Using it from an AI assistant (MCP)

1. **Create an API key** (logged in on the /docs page): `POST /api/v1/api-keys` with `{"name": "my AI tool"}`.
   Copy the `key` (starts with `upm_`). **It is shown only once.**
2. **Connect your AI tool** to `http://localhost:8000/mcp` and send the key as a header: `Authorization: Bearer upm_...`

Examples (client setup changes often, so check your tool's documentation if a command differs):

```bash
# Claude Code
claude mcp add --transport http uptime http://localhost:8000/mcp \
    --header "Authorization: Bearer upm_YOUR_KEY"
```

```jsonc
// Claude Desktop (claude_desktop_config.json) using the "mcp-remote" bridge for local servers
{
  "mcpServers": {
    "uptime": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8000/mcp",
               "--header", "Authorization: Bearer upm_YOUR_KEY"]
    }
  }
}
```

To explore the tools without any AI, use the official inspector: `npx @modelcontextprotocol/inspector`
(choose transport "Streamable HTTP", URL `http://localhost:8000/mcp`, and add the Authorization header).

Then just talk to the assistant: *"Add a monitor for https://example.com"*, *"Is anything down?"*, *"Give me last week's uptime report for monitor 1"*.
Full details: [docs/09-mcp-server.md](docs/09-mcp-server.md).

---

## Run with Docker (PostgreSQL included)

```bash
cp .env.example .env
# edit .env: set SECRET_KEY (make one with: python -c "import secrets; print(secrets.token_urlsafe(48))")
docker compose up --build
```

The app is then at http://localhost:8000. Details and a production checklist: [docs/12-deployment.md](docs/12-deployment.md).

---

## Run the tests

```bash
pytest                    # 91 tests, about 15 seconds, no internet needed
```

Use PostgreSQL for the tests too: `TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/testdb pytest`.
More in [docs/11-testing.md](docs/11-testing.md).

---

## API overview

All routes except `/health*` and register/login need the header `Authorization: Bearer <token>`.

| Method | Path | What it does |
|---|---|---|
| POST | `/api/v1/auth/register` | Create an account |
| POST | `/api/v1/auth/login` | Get a login token |
| GET | `/api/v1/auth/me` | Who am I? |
| POST / GET | `/api/v1/api-keys` | Create / list API keys (for MCP) |
| DELETE | `/api/v1/api-keys/{id}` | Revoke an API key |
| POST | `/api/v1/monitors` | Start watching a website |
| GET | `/api/v1/monitors` | List your monitors (`?limit=&offset=`) |
| GET / PATCH / DELETE | `/api/v1/monitors/{id}` | Read / change (also pause) / delete one monitor |
| POST | `/api/v1/monitors/{id}/check-now` | Check right now |
| GET | `/api/v1/monitors/{id}/checks` | History of checks |
| GET | `/api/v1/monitors/{id}/incidents` | Outages of one monitor |
| GET | `/api/v1/monitors/{id}/report?hours=24` | Uptime report |
| GET | `/api/v1/incidents?only_open=true` | Outages across all monitors |
| GET | `/api/v1/summary` | Overview: how many up, down, paused |
| GET | `/health`, `/health/ready` | Liveness and readiness (no login) |
| any | `/mcp` | The MCP server (API key login) |

---

## Project map

```
uptime-monitor/
├── app/
│   ├── main.py            ← START HERE: plugs everything together
│   ├── config.py          ← all settings
│   ├── database.py        ← database connection
│   ├── models.py          ← the database tables
│   ├── schemas.py         ← shapes of the JSON going in and out
│   ├── security.py        ← passwords, JWT tokens, API keys
│   ├── dependencies.py    ← "current user" and "database session" helpers
│   ├── errors.py          ← our own error types
│   ├── routers/           ← the REST API (thin: receive request, call a service)
│   ├── services/          ← the real logic (used by REST AND MCP)
│   ├── workers/           ← background loops that check websites
│   └── mcp_server.py      ← the MCP server (thin: call the same services)
├── alembic/               ← database migrations
├── tests/                 ← 91 automated tests
├── scripts/smoke_test.py  ← live end-to-end demo
├── docs/                  ← detailed documentation with diagrams  ← READ THESE
├── Dockerfile, docker-compose.yml, .env.example, requirements*.txt
```

## Documentation (read in this order)

| # | Document | You will learn |
|---|---|---|
| 0 | [Start here](docs/00-start-here.md) | How to read this project, and the best order of files |
| 1 | [The big picture](docs/01-big-picture.md) | What the app is made of and how one check flows through it |
| 2 | [FastAPI basics](docs/02-fastapi-basics.md) | FastAPI explained with examples from this project |
| 3 | [FastMCP basics](docs/03-fastmcp-basics.md) | What MCP is and how FastMCP works |
| 4 | [Folder structure](docs/04-folder-structure.md) | Why the code is split into routers, services and models |
| 5 | [Database](docs/05-database.md) | Tables, relationships, indexes, migrations |
| 6 | [Authentication](docs/06-authentication.md) | Passwords, login tokens, API keys |
| 7 | [Monitoring engine](docs/07-monitoring-engine.md) | Scheduler, queue, workers, scaling |
| 8 | [Incidents and alerts](docs/08-incidents-and-alerts.md) | When a site counts as down, and how alerts work |
| 9 | [MCP server](docs/09-mcp-server.md) | Every tool, how auth works, how to connect and extend |
| 10 | [Security](docs/10-security.md) | Protections, and honest limits |
| 11 | [Testing](docs/11-testing.md) | How the tests work and what they prove |
| 12 | [Deployment](docs/12-deployment.md) | Settings, Docker, production checklist |
| 13 | [Glossary and exercises](docs/13-glossary-and-exercises.md) | Every term explained, plus practice tasks |

> The diagrams in the docs use **Mermaid**. They show up automatically on GitHub and in VS Code (install the extension "Markdown Preview Mermaid Support").

## Comment style used in the code

- A block at the **top of each file** explains what the file is for and links to the matching doc.
- A `#` comment **above each function or class** explains what it does in plain words.
- Tool and route **docstrings** (the `"""..."""` text) are not for you: FastAPI shows them on the `/docs` page and FastMCP sends them to the AI. They are written for those readers.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Activate the virtual environment (`source .venv/bin/activate`) and run `pip install -r requirements-dev.txt` |
| `no such table: users` | Run `alembic upgrade head` |
| Monitor says "Private or local addresses are not allowed" | That is the safety feature. For local experiments only: `ALLOW_PRIVATE_URLS=true` |
| A new monitor stays `unknown` | The first check runs within ~10 seconds. If it never runs, check that `RUN_BACKGROUND_WORKERS` is not `false` |
| MCP client gets 401 | Wrong or revoked API key. A login token will NOT work as an MCP key; create an API key |
| Port 8000 already in use | `uvicorn app.main:app --port 8001` |
