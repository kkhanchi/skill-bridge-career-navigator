"""Engine factory — produces a configured SQLAlchemy Engine per ``DATABASE_URL``.

``build_engine`` is called exactly once per app instance at
``init_extensions`` time. It handles the two URL families Phase 2
supports:

- ``sqlite://...`` — local dev and in-memory tests; passes
  ``check_same_thread=False`` because Flask's request model hands
  connections between threads under some WSGI setups.
- ``postgresql://...`` — production; enables ``pool_pre_ping`` so
  idle-timeout connection drops surface as a retry rather than a
  request failure.

Any other scheme is rejected with a :class:`ValueError` so config
mistakes fail loudly at boot instead of producing mysterious runtime
errors.

Design reference: `.kiro/specs/phase-2-persistence/design.md` §db/engine.py.
Requirement reference: R3.4, R10.5.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine


_SUPPORTED_SCHEMES = ("sqlite", "postgresql")


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy :class:`Engine` for *database_url*.

    Args:
        database_url: A SQLAlchemy URL — ``sqlite:///path/to.db``,
            ``sqlite:///:memory:``, or ``postgresql://user:pw@host/db``.
        echo: When True, SQLAlchemy logs every SQL statement.
            Defaults to False (R10.4 — never echo by default).

    Returns:
        An :class:`Engine`. No connections are opened until first use.

    Raises:
        ValueError: The URL's scheme is not supported. Unsupported
            schemes include ``mysql://``, ``oracle://``, and any
            malformed URL that doesn't parse into a known dialect.
    """
    if not database_url:
        raise ValueError("build_engine requires a non-empty DATABASE_URL")

    # Extract the scheme cheaply without depending on ``urllib``; this
    # matches the shape ``create_engine`` itself uses when it inspects
    # the URL, so our error message lines up with what the user sees
    # if they bypass us.
    scheme = database_url.split(":", 1)[0].split("+", 1)[0]
    if scheme not in _SUPPORTED_SCHEMES:
        raise ValueError(
            f"Unsupported DATABASE_URL scheme {scheme!r}; "
            f"expected one of {_SUPPORTED_SCHEMES}"
        )

    if scheme == "sqlite":
        return create_engine(
            database_url,
            echo=echo,
            connect_args={"check_same_thread": False},
        )

    # Postgres. We bundle psycopg3 (`psycopg[binary]`) not psycopg2;
    # rewrite a bare ``postgresql://...`` URL to ``postgresql+psycopg://...``
    # so SQLAlchemy picks the bundled driver instead of failing with
    # "No module named 'psycopg2'". Users who explicitly opt into
    # psycopg2 or asyncpg via the ``postgresql+<driver>://...`` form
    # pass through untouched.
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]

    # ``pool_pre_ping=True`` makes the pool validate a connection
    # before handing it to a caller — cheap for a long-running web
    # process, and the standard fix for connection-reset-after-idle
    # errors seen in managed Postgres offerings.
    return create_engine(database_url, echo=echo, pool_pre_ping=True)
