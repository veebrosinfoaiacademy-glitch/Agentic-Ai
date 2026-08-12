"""FastAPI dependency for authenticated routes.

Any route that needs a signed-in user adds:

    user: UserData = Depends(get_current_user)

and gets three things: the request is rejected before the handler runs if the
token is bad, the handler receives a safe `UserData` rather than a raw Mongo
document, and Swagger shows the padlock plus an Authorize button.
"""

import logging
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.schemas.auth_schemas import UserData
from app.services.auth_service import auth_service
from app.utils.errors import AppError
from app.utils.security import decode_access_token

logger = logging.getLogger("app.auth")

# auto_error=False so a missing header reaches us instead of producing
# Starlette's default 403 body, which would bypass our response envelope.
bearer_scheme = HTTPBearer(
    scheme_name="Bearer",
    description="Paste the access token returned by POST /api/auth/login.",
    auto_error=False,
)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserData:
    """Resolve the caller's identity from the Authorization header.

    Steps: require a Bearer credential, decode and verify the token, then
    load the user it names. Every failure is an AppError with a 401, and none
    of them says which step failed in a way that helps an attacker.

    The header value itself is never logged.
    """
    if credentials is None:
        # Either no Authorization header, or a scheme other than Bearer.
        # Distinguished only for the message, never for the status code.
        header = request.headers.get("Authorization", "")
        if header and not header.lower().startswith("bearer "):
            raise AppError(
                code="TOKEN_INVALID",
                message="Authorization scheme must be Bearer",
                status_code=401,
            )
        raise AppError(
            code="TOKEN_MISSING",
            message="Authentication token is missing",
            status_code=401,
        )

    payload = decode_access_token(credentials.credentials)

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AppError(
            code="TOKEN_INVALID",
            message="Authentication token is invalid",
            status_code=401,
        )

    return auth_service.get_user_by_id(subject)


def require_user(
    request: Request, user: UserData = Depends(get_current_user)
) -> UserData:
    """Protect a route and record who called it.

    A thin wrapper over `get_current_user`, not a second implementation. It
    exists for two reasons:

    * one audit line per authenticated request, naming the user by database
      id — never the token, never the Authorization header;
    * a single place for later phases to add quotas, usage tracking or roles
      without touching fifteen route handlers.
    """
    logger.info(
        "Authorised %s %s for user %s", request.method, request.url.path, user.id
    )
    return user


# Route signatures stay readable: `user: CurrentUser` rather than a
# `= Depends(...)` default on every handler.
CurrentUser = Annotated[UserData, Depends(require_user)]
