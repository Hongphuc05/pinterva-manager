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
