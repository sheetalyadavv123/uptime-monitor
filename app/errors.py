# =============================================================================
# errors.py  -  OUR OWN "SOMETHING WENT WRONG" ERRORS
# =============================================================================
# The "service" files (app/services/) contain the real logic of the app.
# When something goes wrong there (for example "monitor not found"),
# they raise one of the errors below.
#
# Why do we not raise FastAPI's HTTPException directly?
# Because the same service code is used by TWO different front doors:
#   1. The REST API  (needs HTTP status codes like 404)
#   2. The MCP server (needs tool errors, which have no status codes)
#
# So the services raise a neutral error, and each front door translates it:
#   - REST API: app/main.py turns it into a JSON response with a status code.
#   - MCP:      app/mcp_server.py turns it into a clear tool error message.
#
# Read more: docs/04-folder-structure.md
# =============================================================================


# The parent of all our errors. It carries a message and an HTTP status code.
class AppError(Exception):
    status_code = 400

    # Every error is created with a human-readable message, for example AppError("Monitor not found.").
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# The thing you asked for does not exist (or belongs to someone else).
class NotFoundError(AppError):
    status_code = 404


# The request clashes with existing data (for example the email is already used).
class ConflictError(AppError):
    status_code = 409


# The input is well-formed but not acceptable (for example a private URL).
class InvalidInputError(AppError):
    status_code = 422


# Login failed or the token / API key is missing, wrong, or expired.
class AuthenticationError(AppError):
    status_code = 401


# The user hit a limit (for example the maximum number of monitors).
class LimitExceededError(AppError):
    status_code = 403
