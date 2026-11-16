# =============================================================================
# dependencies.py  -  REUSABLE "INGREDIENTS" THAT ROUTES CAN ASK FOR
# =============================================================================
# FastAPI has a feature called DEPENDENCY INJECTION. It sounds scary but the
# idea is simple:
#
#   A route function lists what it needs in its parameters, for example
#   "I need a database session" and "I need the logged-in user".
#   FastAPI then prepares those things and hands them over.
#
# We define the ingredients ONCE here, and every route reuses them:
#
#   SessionDep   -> a database session (closed automatically afterwards)
#   CurrentUser  -> the user who is logged in (or a 401 error if nobody is)
#
# Example of how a route uses them (from routers/monitors.py):
#
#   async def list_my_monitors(session: SessionDep, user: CurrentUser): ...
#
# Read more: docs/02-fastapi-basics.md
# =============================================================================

from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import AuthenticationError
from app.models import User
from app.security import decode_access_token

# Tells FastAPI: "the token comes in the header  Authorization: Bearer <token>".
# `tokenUrl` is where users log in. It also makes the green "Authorize" button
# appear on the interactive docs page (/docs).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# "A database session". Annotated[...] is just a nice way to bundle the type
# with the Depends(...) instruction so we can reuse it as one short name.
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# Finds the logged-in user from the token in the request.
# Steps: read token -> get the user id inside it -> load that user from the database.
async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: SessionDep,
) -> User:
    user_id = decode_access_token(token)  # raises AuthenticationError if invalid
    user = await session.get(User, user_id)
    if user is None:
        raise AuthenticationError("This user no longer exists")
    return user


# "The logged-in user". Any route that has a parameter of this type is
# automatically protected: no valid token means the route never runs.
CurrentUser = Annotated[User, Depends(get_current_user)]
