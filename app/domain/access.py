"""Shared roles and work-domain literals.

These values are persisted in PostgreSQL, so keep them explicit rather than
scattering string comparisons throughout routes and UI-facing commands.
"""

ROLE_ADMIN = "admin"
ROLE_DESIGNER = "designer"
ROLE_DESIGNER_TRELLO = "designer-trello"

WORK_DOMAIN_STANDARD = "standard"
WORK_DOMAIN_DUPLICATE = "duplicate"
WORK_DOMAINS = (WORK_DOMAIN_STANDARD, WORK_DOMAIN_DUPLICATE)
