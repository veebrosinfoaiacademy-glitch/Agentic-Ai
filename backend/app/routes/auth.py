"""Authentication endpoints.

Thin: validate, call the service, wrap the result. No hashing, no JWT
construction, no database access and no try/except — service errors are
already AppErrors and the Phase 2 handlers shape them.

Logout is deliberately absent. Access tokens are stateless and carry their
own expiry, so signing out means the client discarding its token. Adding a
server-side blacklist would mean a database read on every authenticated
request, which is the cost JWTs exist to avoid.
"""

from fastapi import APIRouter, Depends, status

from app.dependencies.auth import get_current_user
from app.schemas.auth_schemas import (
    TokenData,
    UserData,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.schemas.common_schemas import SuccessResponse, success
from app.services.auth_service import auth_service

router = APIRouter(tags=["Authentication"])


@router.post(
    "/register",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
    description=(
        "Registers a user with an email and a password of at least 8 "
        "characters. The email is lowercased and trimmed before storage. "
        "Passwords are hashed with Argon2id and are never stored, returned "
        "or logged in plaintext."
    ),
    responses={
        409: {"description": "An account with this email already exists"},
        422: {"description": "Invalid email or password"},
        503: {"description": "Authentication or database not available"},
    },
)
def register(request: UserRegisterRequest) -> dict:
    user: UserData = auth_service.register(
        email=request.email, password=request.password
    )
    return success(data=user.model_dump(mode="json"), message="User registered successfully")


@router.post(
    "/login",
    response_model=SuccessResponse,
    summary="Log in and receive an access token",
    description=(
        "Returns a JWT access token. An unknown email and an incorrect "
        "password produce the identical response, so this endpoint cannot be "
        "used to discover which addresses are registered.\n\n"
        "Send the token as `Authorization: Bearer <token>`. To log out, "
        "discard it client-side — tokens are stateless and expire on their own."
    ),
    responses={
        401: {"description": "Invalid email or password"},
        503: {"description": "Authentication or database not available"},
    },
)
def login(request: UserLoginRequest) -> dict:
    token: TokenData = auth_service.authenticate(
        email=request.email, password=request.password
    )
    return success(data=token.model_dump(), message="Login successful")


@router.get(
    "/me",
    response_model=SuccessResponse,
    summary="Get the signed-in user",
    description=(
        "Protected. Requires `Authorization: Bearer <token>`. Returns the "
        "account that owns the token — never a password hash."
    ),
    responses={
        401: {"description": "Token missing, invalid, expired, or user gone"},
    },
)
def read_current_user(user: UserData = Depends(get_current_user)) -> dict:
    return success(
        data=user.model_dump(mode="json"),
        message="Current user retrieved successfully",
    )
