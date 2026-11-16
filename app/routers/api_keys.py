# =============================================================================
# routers/api_keys.py  -  MANAGE API KEYS FOR THE MCP SERVER
# =============================================================================
#   POST   /api/v1/api-keys        create a key (the secret is shown ONCE)
#   GET    /api/v1/api-keys        list your keys (secrets are never shown again)
#   DELETE /api/v1/api-keys/{id}   revoke a key
#
# Why a separate key and not the login token? Login tokens expire quickly and
# are meant for people. An AI tool needs something long-lived that you can
# revoke on its own without logging out everywhere.
#
# Read more: docs/06-authentication.md
# =============================================================================

from fastapi import APIRouter, Response

from app.dependencies import CurrentUser, SessionDep
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from app.services import api_keys as api_key_service

router = APIRouter(prefix="/api/v1/api-keys", tags=["API keys"])


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_key(payload: ApiKeyCreate, session: SessionDep, user: CurrentUser):
    """Create an API key. Copy it now: it cannot be shown again."""
    api_key, full_key = await api_key_service.create_api_key(session, user.id, payload.name)
    # ApiKeyCreated = the normal key fields + the secret `key`.
    return ApiKeyCreated(**ApiKeyRead.model_validate(api_key).model_dump(), key=full_key)


@router.get("", response_model=list[ApiKeyRead])
async def list_keys(session: SessionDep, user: CurrentUser):
    """List your API keys (only the first characters of each key are shown)."""
    return await api_key_service.list_api_keys(session, user.id)


# `{key_id}` in the path becomes the function parameter `key_id`.
# FastAPI also converts it to an int and answers 422 if it is not a number.
@router.delete("/{key_id}", status_code=204)
async def delete_key(key_id: int, session: SessionDep, user: CurrentUser):
    """Revoke an API key. It stops working immediately."""
    await api_key_service.delete_api_key(session, user.id, key_id)
    return Response(status_code=204)  # 204 = success, nothing to send back
