"""Schemas for AI usage limits.

Nothing here accepts input from a client. Usage is derived entirely from the
authenticated user and the server clock, so there is no request model at all —
which is also why there is no way for a caller to influence whose quota is
being read or spent.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class UsageWindow(str, Enum):
    """The rolling periods a limit can apply to."""

    HOUR = "hour"
    DAY = "day"


class WindowUsage(BaseModel):
    """One window's state, as the API presents it."""

    used: int = Field(ge=0, description="Requests made in the current window.")
    limit: int = Field(
        ge=0, description="Maximum allowed in the window. 0 means unlimited."
    )
    remaining: int | None = Field(
        default=None,
        description="Requests left, or null when the limit is disabled.",
    )
    resets_at: datetime = Field(description="When this window rolls over (UTC).")


class UsageData(BaseModel):
    """`data` payload for GET /api/usage.

    Deliberately free of database detail: no document ids, no window start
    keys, no collection names. Just what a client needs to show a meter.
    """

    hour: WindowUsage
    day: WindowUsage
    limited: bool = Field(
        description="Whether any limit is currently in force for this user."
    )
