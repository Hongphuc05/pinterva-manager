from enum import Enum


class ErrorClass(str, Enum):  # noqa: UP042 -- str+Enum shape mandated by claude.md, keep verbatim
    VALIDATION = "VALIDATION"
    AUTH = "AUTH"
    RATE_LIMIT = "RATE_LIMIT"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    EXTERNAL_CHANGED = "EXTERNAL_CHANGED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    PERMANENT_EXTERNAL = "PERMANENT_EXTERNAL"
    BUG = "BUG"
