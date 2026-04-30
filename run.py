"""Development entry point.

Run with ``python run.py``. Uses Flask's built-in server with debug mode,
suitable only for local development.

For production, use ``wsgi.py`` + gunicorn:
    gunicorn -w 1 wsgi:application

(One worker because Phase 1 repositories are in-memory per-process.)
"""

from __future__ import annotations

from app import create_app

if __name__ == "__main__":
    create_app("dev").run(host="0.0.0.0", port=5000, debug=True)
