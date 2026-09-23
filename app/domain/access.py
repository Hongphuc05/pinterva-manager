"""Shared roles and work-domain literals.

These values are persisted in PostgreSQL, so keep them explicit rather than
scattering string comparisons throughout routes and UI-facing commands.
"""

ROLE_ADMIN = "admin"
ROLE_DESIGNER = "designer"
ROLE_DESIGNER_TRELLO = "designer-trello"
ROLE_SUPPORT = "support"

WORK_DOMAIN_STANDARD = "standard"
WORK_DOMAIN_DUPLICATE = "duplicate"
WORK_DOMAINS = (WORK_DOMAIN_STANDARD, WORK_DOMAIN_DUPLICATE)

DUPLICATE_CHECK_UNCHECK = "uncheck"
DUPLICATE_CHECK_DUPLICATE = "duplicate"
DUPLICATE_CHECK_NON_DUPLICATE = "non_duplicate"
DUPLICATE_CHECK_STATUSES = (
    DUPLICATE_CHECK_UNCHECK,
    DUPLICATE_CHECK_DUPLICATE,
    DUPLICATE_CHECK_NON_DUPLICATE,
)

# A classified order remains visible to Support after it leaves the Waiting
# queue, but it is read-only there.  Keep this separate from
# DUPLICATE_CHECK_STATUSES because ``uncheck`` is not a completed
# classification and must not widen Support's read scope.
SUPPORT_CLASSIFIED_STATUSES = frozenset(
    {
        DUPLICATE_CHECK_DUPLICATE,
        DUPLICATE_CHECK_NON_DUPLICATE,
    }
)

# Support may classify only orders that are still waiting for the duplicate
# check.  Keep legacy pre-WAITING values here because production data can still
# contain them while the state migration is being rolled out.
SUPPORT_CLASSIFICATION_STATES = frozenset(
    {
        "OPEN",
        "WAITING",
        "OPEN_FOR_ALLOCATION",
        "DISCOVERED",
        "PENDING",
    }
)

# Support may inspect every order currently being worked on, but this scope is
# read-only.  Keep legacy ASSIGNED alongside canonical IN_PROGRESS because
# older rows can still carry that value while state normalization is rolled out.
SUPPORT_READ_ONLY_DOING_STATES = frozenset({"IN_PROGRESS", "ASSIGNED"})
