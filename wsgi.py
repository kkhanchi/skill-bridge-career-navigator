"""Production WSGI entry point.

Use with a WSGI server such as gunicorn::

    gunicorn -w 1 wsgi:application

Phase 1 runs a single worker because repositories are in-memory per
process. Multi-worker support arrives with the Phase 2 database.
"""

from __future__ import annotations

from app import create_app

application = create_app("prod")
