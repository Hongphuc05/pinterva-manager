"""CLI wrapper for the PostgreSQL-backed comparison runner."""

from backend.postgres_compare import main

if __name__ == "__main__":
    raise SystemExit(main())
