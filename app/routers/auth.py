# =============================================================================
# routers/auth.py  -  REGISTER, LOGIN, AND "WHO AM I?"
# =============================================================================
#   POST /api/v1/auth/register   create an account
#   POST /api/v1/auth/login      exchange email + password for a token
#   GET  /api/v1/auth/me         show the logged-in user
#
# A router file is deliberately THIN: it receives the request, calls a service
# function that does the real work, and returns the result.
#
# Read more: docs/06-authentication.md
# =============================================================================

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.dependencies import CurrentUser, SessionDep
from app.schemas import Token, UserCreate, UserRead
from app.security import create_access_token
from app.services import users as user_service

# prefix: every route below starts with /api/v1/auth
# tags: groups the routes in the docs page (/docs)
router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


# `payload: UserCreate` tells FastAPI: "the request body is JSON shaped like
# UserCreate". FastAPI parses it and validates it. If the email is invalid
# or the password is too short, FastAPI answers 422 and our code never runs.
# `response_model=UserRead` means: only send back the fields of UserRead.
@router.post("/register", response_model=UserRead, status_code=201)
async def register(payload: UserCreate, session: SessionDep):
    """Create a new account."""
    return await user_service.register_user(session, payload.email, payload.password)


# Login uses a standard "form" format (OAuth2PasswordRequestForm) because that
# is what the /docs "Authorize" button sends. The form calls the email field
# `username`, so we read the email from `form.username`.
@router.post("/login", response_model=Token)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
):
    """Log in with email and password. Returns a token to use on other routes."""
    user = await user_service.authenticate_user(session, form.username, form.password)
    return Token(access_token=create_access_token(user.id))


# `user: CurrentUser` makes this route require a valid token.
@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser):
    """Show the account of the logged-in user."""
    return user
