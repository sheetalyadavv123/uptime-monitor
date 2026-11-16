# 3. FastMCP basics

## What is MCP?

**MCP (Model Context Protocol)** is an open standard that lets an AI assistant use outside tools and data.

Think of the USB port. Before USB, every device needed its own special cable. MCP is the "USB port" for AI: **any** MCP-capable assistant can plug into **any** MCP server.

```mermaid
flowchart LR
    subgraph Client["MCP client (inside an AI app)"]
        AI["The AI model"]
    end
    subgraph Server["MCP server (our app)"]
        T["Tools"]
        R["Resources"]
        P["Prompts"]
    end
    AI <-- "MCP protocol<br/>(JSON messages over HTTP)" --> Server
    Server --> App["Our services and database"]
```

## What is FastMCP?

FastMCP is a Python library for writing MCP servers quickly. You write normal Python functions and add a decorator. FastMCP does the protocol work: describing your tools to the AI, checking inputs, and sending results back.

It is to MCP what FastAPI is to web APIs.

| | FastAPI | FastMCP |
|---|---|---|
| Who calls it? | Apps, browsers, scripts | AI assistants |
| You write | Routes (`@router.get`) | Tools (`@mcp.tool`) |
| Described to the caller by | `/docs` (OpenAPI) | The MCP protocol (tool list) |
| In this project | `app/routers/` | `app/mcp_server.py` |

## The three things an MCP server can offer

| Kind | What it is | Who triggers it | Example in this project |
|---|---|---|---|
| **Tool** | An action. May change data. | The AI decides | `add_monitor`, `get_incidents` |
| **Resource** | Read-only data with an address (a URI) | The app or the user attaches it | `uptime://summary` |
| **Prompt** | A reusable instruction template | The user picks it (like a slash command) | `investigate_incident` |

## A tool in 6 lines

From `app/mcp_server.py` (simplified):

```python
@mcp.tool(annotations={"readOnlyHint": True})
async def get_monitor(monitor_id: int) -> MonitorRead:
    """Get the details and current status of one monitor by its id."""
    async with SessionLocal() as session:
        monitor = await monitor_service.get_monitor(session, _current_user_id(), monitor_id)
        return MonitorRead.model_validate(monitor)
```

FastMCP reads this function and automatically builds the tool description:

```mermaid
flowchart TD
    F["Your Python function"] --> N["function name<br/>-> tool name: get_monitor"]
    F --> D["docstring<br/>-> description the AI reads"]
    F --> I["parameters + type hints<br/>-> input schema: monitor_id must be an integer"]
    F --> O["return type<br/>-> structured output (MonitorRead)"]
    F --> A["annotations<br/>-> hints: this tool only reads"]
```

> **Very important:** the docstring of a tool is read by the **AI**. It decides *when* to call the tool from that text. So write it like instructions to a smart colleague: what it does, and what the parameters mean.

## How a conversation uses tools

```mermaid
sequenceDiagram
    autonumber
    participant U as You
    participant A as AI assistant
    participant S as MCP server

    A->>S: connect, ask "what tools do you have?"
    S-->>A: list of 10 tools with descriptions and input schemas
    U->>A: "Start watching example.com"
    A->>A: decides to call add_monitor
    A->>S: call add_monitor(name="Example", url="https://example.com")
    S-->>A: the new monitor (JSON)
    A-->>U: "Done. I am watching https://example.com every 60 seconds."
```

The AI never sees our code. It only sees the tool list. That is why clear descriptions and clear error messages matter.

## Transports: how client and server talk

| Transport | How it works | When used |
|---|---|---|
| stdio | The client starts your program and talks through its input/output | Local tools on your own computer |
| **Streamable HTTP** | Normal HTTP requests to a URL | Servers on a network. **We use this.** |

Because our MCP server is an HTTP endpoint (`/mcp`), it can live inside the same FastAPI app and be protected by keys.

## Authentication

Our MCP server must know **which user** is calling, so that people only see their own monitors.

```mermaid
sequenceDiagram
    autonumber
    participant AI as AI app
    participant F as FastMCP
    participant V as ApiKeyVerifier
    participant DB as Database
    participant T as Your tool

    AI->>F: request + header  Authorization: Bearer upm_abc...
    F->>V: verify_token("upm_abc...")
    V->>DB: find user by hash of the key
    alt key is unknown
        V-->>F: None
        F-->>AI: 401 Unauthorized (no tool runs)
    else key is valid
        V-->>F: AccessToken(claims = {user_id: 7})
        F->>T: run the tool
        T->>T: get_access_token() -> user_id 7
        T-->>AI: result for user 7 only
    end
```

In code: `ApiKeyVerifier` (a `TokenVerifier`) in `app/mcp_server.py`, and `_current_user_id()` inside every tool. More in [doc 6](06-authentication.md).

## Middleware: code that wraps every call

`ErrorTranslationMiddleware` in `mcp_server.py` wraps every tool call. If a service raises `NotFoundError("Monitor not found.")`, it converts it into a `ToolError` with the same message, so the AI can tell the user something useful.

```mermaid
flowchart LR
    C["Tool call"] --> M["Middleware"] --> T["Your tool"]
    T -- "raises NotFoundError" --> M
    M -- "raises ToolError('Monitor not found.')" --> AI["AI sees a clear message"]
```

## How the MCP server lives inside the FastAPI app

```mermaid
flowchart TB
    subgraph One["One uvicorn process"]
        FA["FastAPI app"]
        FA -- "/api/v1/..., /health, /docs" --> Routes["Routers"]
        FA -- "everything else (mounted at '/')" --> MCPApp["FastMCP web app<br/>answers /mcp"]
    end
```

Two details in `app/main.py`:
1. `mcp_app = mcp.http_app(path="/mcp")` creates the MCP web app.
2. `app.mount("/", mcp_app)` plugs it in **last**, so the normal routes win first. The MCP app also needs its own startup code, which we run inside our `lifespan` with `async with mcp_app.lifespan(app)`.

## One core, two front doors

```mermaid
flowchart LR
    RE["REST: POST /api/v1/monitors"] --> SV["monitor_service.create_monitor()"]
    MC["MCP: add_monitor tool"] --> SV
```

Both call the **same function**. The rules (minimum interval, no private addresses, per-user limit) are identical everywhere. See [doc 4](04-folder-structure.md).

## Where to look in the code

| Concept | Where |
|---|---|
| Server object, instructions | `mcp = FastMCP(...)` in `app/mcp_server.py` |
| Tools | `@mcp.tool` functions in `app/mcp_server.py` |
| Resource | `@mcp.resource("uptime://summary")` |
| Prompt | `@mcp.prompt` |
| Auth | `ApiKeyVerifier` |
| Error translation | `ErrorTranslationMiddleware` |
| Mounting | `app/main.py` |
| Tests that talk to it like an AI would | `tests/test_mcp.py` |

Next: [4. Folder structure](04-folder-structure.md) or jump to [9. The MCP server in detail](09-mcp-server.md).
