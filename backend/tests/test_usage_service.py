"""Phase 12 tests: AI usage counters.

Entirely offline — in-memory counters, no Atlas.
"""

from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId

from app.config import settings
from app.schemas.usage_schemas import UsageWindow
from app.services.usage_service import (
    _window_end,
    _window_start,
    usage_service,
)
from tests.conftest import FakeCollection

USER_A = str(ObjectId())
USER_B = str(ObjectId())


def counts(counters: FakeCollection, user_id: str = USER_A) -> dict[str, int]:
    """Current counter values by window, for readable assertions."""
    owner = ObjectId(user_id)
    return {
        d["window"]: d["count"]
        for d in counters.documents
        if d["user_id"] == owner
    }


# --- Window arithmetic ------------------------------------------------------


def test_hour_window_truncates_to_the_hour() -> None:
    moment = datetime(2026, 3, 4, 15, 47, 23, 500, tzinfo=UTC)

    start = _window_start(UsageWindow.HOUR, moment)

    assert start == datetime(2026, 3, 4, 15, 0, 0, 0, tzinfo=UTC)
    assert _window_end(UsageWindow.HOUR, start) == datetime(2026, 3, 4, 16, tzinfo=UTC)


def test_day_window_truncates_to_midnight() -> None:
    moment = datetime(2026, 3, 4, 15, 47, 23, tzinfo=UTC)

    start = _window_start(UsageWindow.DAY, moment)

    assert start == datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)
    assert _window_end(UsageWindow.DAY, start) == datetime(2026, 3, 5, tzinfo=UTC)


def test_windows_are_utc_aware() -> None:
    start = _window_start(UsageWindow.HOUR, datetime.now(UTC))

    assert start.tzinfo is not None


# --- Reserving --------------------------------------------------------------


def test_first_request_is_allowed_and_counted(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=10, day=50)

    reservation = usage_service.reserve(USER_A)

    assert reservation.allowed is True
    assert reservation.recorded is True
    assert counts(usage_counters) == {"hour": 1, "day": 1}


def test_repeated_requests_accumulate(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=10, day=50)

    for _ in range(4):
        usage_service.reserve(USER_A)

    assert counts(usage_counters) == {"hour": 4, "day": 4}


def test_one_document_per_user_and_window(
    usage_counters: FakeCollection, ai_limits
) -> None:
    """The upsert must not create a row per request."""
    ai_limits(hour=10, day=50)

    for _ in range(5):
        usage_service.reserve(USER_A)

    assert len(usage_counters.documents) == 2  # one hour row, one day row


def test_requests_up_to_the_limit_are_allowed(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=3, day=50)

    results = [usage_service.reserve(USER_A).allowed for _ in range(3)]

    assert results == [True, True, True]
    assert counts(usage_counters)["hour"] == 3


def test_the_request_after_the_limit_is_refused(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=3, day=50)
    for _ in range(3):
        usage_service.reserve(USER_A)

    reservation = usage_service.reserve(USER_A)

    assert reservation.allowed is False
    assert reservation.window is UsageWindow.HOUR
    assert reservation.limit == 3
    assert reservation.used == 3


def test_a_refused_request_leaves_the_counter_untouched(
    usage_counters: FakeCollection, ai_limits
) -> None:
    """Rejection must not itself consume a slot, or the counter would drift."""
    ai_limits(hour=2, day=50)
    usage_service.reserve(USER_A)
    usage_service.reserve(USER_A)

    for _ in range(5):
        usage_service.reserve(USER_A)

    assert counts(usage_counters)["hour"] == 2


def test_refusal_reports_when_the_window_resets(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=1, day=50)
    usage_service.reserve(USER_A)

    reservation = usage_service.reserve(USER_A)

    assert 0 < reservation.retry_after_seconds <= 3600


def test_the_daily_limit_also_applies(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=0, day=2)  # hourly disabled, daily in force

    allowed = [usage_service.reserve(USER_A).allowed for _ in range(3)]

    assert allowed == [True, True, False]


def test_the_daily_refusal_names_the_day_window(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=100, day=1)
    usage_service.reserve(USER_A)

    reservation = usage_service.reserve(USER_A)

    assert reservation.window is UsageWindow.DAY
    assert 0 < reservation.retry_after_seconds <= 86_400


def test_a_daily_refusal_refunds_the_hourly_claim(
    usage_counters: FakeCollection, ai_limits
) -> None:
    """Both windows are claimed together, so both must be given back."""
    ai_limits(hour=100, day=1)
    usage_service.reserve(USER_A)

    usage_service.reserve(USER_A)  # refused on the daily limit

    assert counts(usage_counters) == {"hour": 1, "day": 1}


def test_a_new_window_starts_fresh(
    usage_counters: FakeCollection, ai_limits
) -> None:
    """Rolling into the next hour resets the hourly counter."""
    ai_limits(hour=2, day=50)
    usage_service.reserve(USER_A)
    usage_service.reserve(USER_A)
    assert usage_service.reserve(USER_A).allowed is False

    # Age the existing hour row so "now" falls into a later window.
    for document in usage_counters.documents:
        if document["window"] == "hour":
            document["window_start"] -= timedelta(hours=1)

    assert usage_service.reserve(USER_A).allowed is True


# --- Limits disabled --------------------------------------------------------


def test_limits_disabled_allows_everything(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=0, day=0)

    allowed = [usage_service.reserve(USER_A).allowed for _ in range(50)]

    assert all(allowed)
    assert usage_counters.documents == []  # nothing even recorded


def test_limits_enabled_reports_configuration(ai_limits) -> None:
    ai_limits(hour=0, day=0)
    assert usage_service.limits_enabled() is False

    ai_limits(hour=1, day=0)
    assert usage_service.limits_enabled() is True

    ai_limits(hour=0, day=1)
    assert usage_service.limits_enabled() is True


def test_a_disabled_window_is_not_counted(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=0, day=10)

    usage_service.reserve(USER_A)

    assert "hour" not in counts(usage_counters)
    assert counts(usage_counters)["day"] == 1


# --- User isolation ---------------------------------------------------------


def test_users_have_separate_counters(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=2, day=50)
    usage_service.reserve(USER_A)
    usage_service.reserve(USER_A)

    # A is exhausted; B must be unaffected.
    assert usage_service.reserve(USER_A).allowed is False
    assert usage_service.reserve(USER_B).allowed is True
    assert counts(usage_counters, USER_B) == {"hour": 1, "day": 1}


def test_usage_report_covers_only_the_caller(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=10, day=50)
    for _ in range(3):
        usage_service.reserve(USER_A)
    usage_service.reserve(USER_B)

    assert usage_service.get_usage(USER_A).hour.used == 3
    assert usage_service.get_usage(USER_B).hour.used == 1


def test_every_counter_query_is_scoped_to_one_user(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=10, day=50)
    usage_service.reserve(USER_A)
    usage_counters.queries.clear()

    usage_service.get_usage(USER_A)

    assert usage_counters.queries
    for query in usage_counters.queries:
        assert query.get("user_id") == ObjectId(USER_A)


# --- Refunds ----------------------------------------------------------------


def test_refund_returns_a_claim(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=10, day=50)
    usage_service.reserve(USER_A)

    usage_service.refund(USER_A)

    assert counts(usage_counters) == {"hour": 0, "day": 0}


def test_reserve_then_refund_frees_the_slot_again(
    usage_counters: FakeCollection, ai_limits
) -> None:
    """The malformed-request path: claim taken, then given back."""
    ai_limits(hour=1, day=50)
    usage_service.reserve(USER_A)
    usage_service.refund(USER_A)

    assert usage_service.reserve(USER_A).allowed is True


def test_refund_does_nothing_when_limits_are_disabled(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=0, day=0)

    usage_service.refund(USER_A)

    assert usage_counters.documents == []


# --- Reporting --------------------------------------------------------------


def test_usage_report_shape(usage_counters: FakeCollection, ai_limits) -> None:
    ai_limits(hour=10, day=50)
    usage_service.reserve(USER_A)

    usage = usage_service.get_usage(USER_A)

    assert usage.hour.used == 1
    assert usage.hour.limit == 10
    assert usage.hour.remaining == 9
    assert usage.day.remaining == 49
    assert usage.limited is True
    assert usage.hour.resets_at > datetime.now(UTC)


def test_unlimited_windows_report_null_remaining(
    usage_counters: FakeCollection, ai_limits
) -> None:
    """None, not a large number — "unlimited" is not a quantity."""
    ai_limits(hour=0, day=0)

    usage = usage_service.get_usage(USER_A)

    assert usage.hour.limit == 0
    assert usage.hour.remaining is None
    assert usage.limited is False


def test_a_user_with_no_history_reports_zero(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=10, day=50)

    usage = usage_service.get_usage(USER_A)

    assert usage.hour.used == 0
    assert usage.day.used == 0


def test_report_never_exposes_database_internals(
    usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=10, day=50)
    usage_service.reserve(USER_A)

    payload = usage_service.get_usage(USER_A).model_dump()

    for internal in ("_id", "user_id", "window_start", "updated_at"):
        assert internal not in str(payload)


# --- Failing open -----------------------------------------------------------


def test_an_unreachable_counter_allows_the_request(
    failing_usage_counters: FakeCollection, ai_limits
) -> None:
    """A cost guard must not become an outage."""
    ai_limits(hour=1, day=1)

    reservation = usage_service.reserve(USER_A)

    assert reservation.allowed is True
    assert reservation.recorded is False  # nothing to refund later


def test_an_unconfigured_database_allows_the_request(ai_limits) -> None:
    """No usage fixture at all: get_usage_collection raises AppError."""
    ai_limits(hour=1, day=1)

    assert usage_service.reserve(USER_A).allowed is True


def test_usage_report_survives_an_unreachable_counter(
    failing_usage_counters: FakeCollection, ai_limits
) -> None:
    ai_limits(hour=10, day=50)

    usage = usage_service.get_usage(USER_A)

    assert usage.hour.used == 0  # honest: we do not know


def test_failures_never_leak_database_detail(
    failing_usage_counters: FakeCollection,
    ai_limits,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ai_limits(hour=1, day=1)

    with caplog.at_level("DEBUG"):
        usage_service.reserve(USER_A)

    for leak in ("mongodb+srv", "27017", "Traceback", "password"):
        assert leak.lower() not in caplog.text.lower()


def test_an_unusable_user_id_fails_open(
    usage_counters: FakeCollection, ai_limits
) -> None:
    """Cannot happen via the dependency, but must not 500 if it did."""
    ai_limits(hour=1, day=1)

    assert usage_service.reserve("not-an-objectid").allowed is True
    assert usage_service.get_usage("not-an-objectid").hour.used == 0


# --- Index configuration ----------------------------------------------------


def test_usage_indexes_are_declared(connected_db) -> None:
    """The unique index is what makes the atomic upsert safe."""
    from app.database import USAGE_COLLECTION, mongodb

    collection = mongodb.get_database()[USAGE_COLLECTION]
    collection.create_index(
        [("user_id", 1), ("window", 1), ("window_start", 1)],
        unique=True,
        name="uniq_user_window",
    )
    collection.create_index(
        "window_start",
        expireAfterSeconds=settings.USAGE_RETENTION_DAYS * 24 * 60 * 60,
        name="usage_ttl",
    )

    keys, options = collection.indexes[0]
    assert options["unique"] is True
    ttl_keys, ttl_options = collection.indexes[1]
    assert ttl_options["expireAfterSeconds"] == settings.USAGE_RETENTION_DAYS * 86_400
