"""Per-user AI usage counters.

Guards provider spend: one account cannot burn the whole Groq budget. Counts
live in MongoDB as one document per (user, window kind, window start), updated
with a single atomic upsert.

Two properties matter more than anything else here.

**Reserving is atomic.** `find_one_and_update` with `$inc` and `upsert=True`
increments and returns the new value in one round trip, so two concurrent
requests can never both see "one slot left". A read-then-write check would
let them.

**A broken counter must not break the product.** If the usage collection is
unreachable, requests are allowed through with a warning. A quota is a cost
guard, not a security boundary — refusing all AI service because a counter is
down is worse than briefly not counting. Authentication continues to fail
closed; only this fails open.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app.config import settings
from app.database import get_usage_collection
from app.schemas.usage_schemas import UsageData, UsageWindow, WindowUsage
from app.utils.errors import AppError

logger = logging.getLogger("app.usage")


@dataclass(frozen=True)
class Reservation:
    """The outcome of trying to claim one AI request."""

    allowed: bool
    window: UsageWindow | None = None
    limit: int = 0
    used: int = 0
    retry_after_seconds: int = 0
    # False when the counter was unreachable, so nothing needs refunding.
    recorded: bool = False


def _window_start(window: UsageWindow, moment: datetime) -> datetime:
    """Truncate a timestamp to the start of its window.

    Fixed windows rather than sliding: one document per period, trivially
    explainable, and no per-request history to store. The trade-off is a
    possible burst across a boundary, which is acceptable at this scale.
    """
    if window is UsageWindow.HOUR:
        return moment.replace(minute=0, second=0, microsecond=0)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _window_end(window: UsageWindow, start: datetime) -> datetime:
    return start + (timedelta(hours=1) if window is UsageWindow.HOUR else timedelta(days=1))


def _limit_for(window: UsageWindow) -> int:
    return (
        settings.AI_RATE_LIMIT_PER_HOUR
        if window is UsageWindow.HOUR
        else settings.AI_RATE_LIMIT_PER_DAY
    )


def _collection():
    """The usage collection, or None if it cannot be reached.

    `get_usage_collection` raises AppError when the database is not
    configured, and PyMongo raises its own errors when it is unreachable.
    Both must be swallowed here: failing open is the whole point, and letting
    either escape would turn a counter outage into a 503 on every AI request.
    """
    try:
        return get_usage_collection()
    except (AppError, PyMongoError) as exc:
        logger.warning(
            "Usage counters unavailable (%s); requests proceed uncounted",
            type(exc).__name__,
        )
        return None


def _to_object_id(user_id: str) -> ObjectId | None:
    """Parse the caller's id. Never accepts one from a request body."""
    if not isinstance(user_id, str) or not user_id.strip():
        return None
    try:
        return ObjectId(user_id)
    except (InvalidId, TypeError):
        return None


class UsageService:
    """Reserves, refunds and reports AI usage for one user at a time."""

    @staticmethod
    def limits_enabled() -> bool:
        """True when at least one window has a limit configured."""
        return settings.AI_RATE_LIMIT_PER_HOUR > 0 or settings.AI_RATE_LIMIT_PER_DAY > 0

    def _adjust(
        self, owner: ObjectId, window: UsageWindow, start: datetime, delta: int
    ) -> int | None:
        """Apply `delta` to one window's counter and return the new value.

        None means the counter could not be reached.
        """
        collection = _collection()
        if collection is None:
            return None

        try:
            document = collection.find_one_and_update(
                {"user_id": owner, "window": window.value, "window_start": start},
                {"$inc": {"count": delta}, "$set": {"updated_at": datetime.now(UTC)}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except PyMongoError as exc:
            # Type name only — PyMongo messages embed cluster hostnames.
            logger.warning(
                "Usage counter unavailable (%s); allowing the request uncounted",
                type(exc).__name__,
            )
            return None
        return int(document.get("count", 0))

    def reserve(self, user_id: str) -> Reservation:
        """Claim one AI request for this user.

        Increments first and checks the result, rather than checking then
        incrementing. If the increment pushes the user past a limit the claim
        is refunded immediately and refused, so a rejected request leaves the
        counter exactly as it found it.
        """
        if not self.limits_enabled():
            return Reservation(allowed=True)

        owner = _to_object_id(user_id)
        if owner is None:
            # Cannot happen through the dependency, which only ever passes an
            # authenticated user's id. Fail open rather than reject.
            logger.warning("Usage reserve called with an unusable user id")
            return Reservation(allowed=True)

        now = datetime.now(UTC)
        claimed: list[tuple[UsageWindow, datetime]] = []

        for window in (UsageWindow.HOUR, UsageWindow.DAY):
            limit = _limit_for(window)
            if limit <= 0:
                continue

            start = _window_start(window, now)
            count = self._adjust(owner, window, start, +1)

            if count is None:
                # Counter unreachable. Undo anything already claimed so the
                # request is not half-counted, then allow it through.
                self._refund_windows(owner, claimed)
                return Reservation(allowed=True)

            claimed.append((window, start))

            if count > limit:
                # Over the line: give back every claim from this attempt,
                # including this one, and report when they can retry.
                self._refund_windows(owner, claimed)
                retry_after = max(1, int((_window_end(window, start) - now).total_seconds()))
                logger.info(
                    "Usage limit reached for user %s (%s window: %d/%d)",
                    owner,
                    window.value,
                    count - 1,
                    limit,
                )
                return Reservation(
                    allowed=False,
                    window=window,
                    limit=limit,
                    used=count - 1,
                    retry_after_seconds=retry_after,
                )

        return Reservation(allowed=True, recorded=bool(claimed))

    def _refund_windows(
        self, owner: ObjectId, claimed: list[tuple[UsageWindow, datetime]]
    ) -> None:
        for window, start in claimed:
            self._adjust(owner, window, start, -1)

    def refund(self, user_id: str) -> None:
        """Return a reservation that produced nothing.

        Called when a request fails after reserving — a malformed body, or a
        provider error. The user asked for work they never received, so the
        claim is given back.
        """
        if not self.limits_enabled():
            return

        owner = _to_object_id(user_id)
        if owner is None:
            return

        now = datetime.now(UTC)
        for window in (UsageWindow.HOUR, UsageWindow.DAY):
            if _limit_for(window) <= 0:
                continue
            self._adjust(owner, window, _window_start(window, now), -1)

    def get_usage(self, user_id: str) -> UsageData:
        """Report this user's current counts. Never another user's.

        Read-only, and scoped by owner in the query itself.
        """
        owner = _to_object_id(user_id)
        now = datetime.now(UTC)
        windows: dict[UsageWindow, WindowUsage] = {}

        for window in (UsageWindow.HOUR, UsageWindow.DAY):
            limit = _limit_for(window)
            start = _window_start(window, now)
            used = 0

            collection = _collection() if owner is not None else None
            if collection is not None:
                try:
                    document = collection.find_one(
                        {
                            "user_id": owner,
                            "window": window.value,
                            "window_start": start,
                        }
                    )
                    used = max(0, int(document.get("count", 0))) if document else 0
                except PyMongoError as exc:
                    # Reporting zero is honest here: we genuinely do not know,
                    # and inventing a number would mislead the meter.
                    logger.warning(
                        "Could not read usage (%s); reporting zero",
                        type(exc).__name__,
                    )

            windows[window] = WindowUsage(
                used=used,
                limit=limit,
                remaining=max(0, limit - used) if limit > 0 else None,
                resets_at=_window_end(window, start),
            )

        return UsageData(
            hour=windows[UsageWindow.HOUR],
            day=windows[UsageWindow.DAY],
            limited=self.limits_enabled(),
        )


usage_service = UsageService()
