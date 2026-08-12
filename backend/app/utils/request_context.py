"""Per-request correlation IDs.

Every response carries an `X-Request-ID` header and every log line emitted
while handling that request carries the same value. When someone reports "it
failed at 14:32", the id in their response finds the exact log records.

The id is deliberately NOT added to the JSON envelope. The success and error
shapes are a contract several test modules assert by exact equality, and a
header is the conventional place for correlation data anyway.
"""

import logging
import re
import secrets
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"

# Generated ids are 16 hex characters: short enough to read aloud over a
# support call, long enough that collisions are not a practical concern.
_GENERATED_ID_BYTES = 8

# An inbound id is attacker-controlled and ends up in log files. Without a
# whitelist someone could inject newlines and forge log records, or push a
# megabyte of text through every log line. Alphanumerics, dash and underscore
# cover every sane client id (UUIDs, ULIDs, trace ids) and nothing else.
MAX_REQUEST_ID_LENGTH = 64
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,%d}$" % MAX_REQUEST_ID_LENGTH)

# ContextVar rather than a module global: each request gets its own value even
# when several are in flight, and it is readable from anywhere without being
# threaded through every function signature.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    """A fresh random correlation id."""
    return secrets.token_hex(_GENERATED_ID_BYTES)


def sanitise_request_id(candidate: str | None) -> str:
    """Return a safe id: the client's if it is acceptable, otherwise a new one.

    Rejected rather than cleaned. Stripping bad characters would silently
    change the id the client thinks it sent, which defeats correlation; a
    fresh id is honest about the fact we did not accept theirs.
    """
    if candidate and _SAFE_REQUEST_ID.match(candidate):
        return candidate
    return new_request_id()


def set_request_id(request_id: str) -> None:
    """Bind the id to the current context."""
    _request_id.set(request_id)


def get_request_id() -> str:
    """The current request's id, or "-" outside a request."""
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Injects `request_id` into every log record so the format can use it.

    A filter rather than a custom formatter, so the application's existing
    logging configuration keeps working and nothing else has to change.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True
