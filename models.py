"""Shim: re-exports `app.core.models` for the existing Streamlit UI and tests.

The canonical module now lives at `app/core/models.py`. This shim exists so
that `from models import UserProfile` and similar imports in the Streamlit UI
and legacy tests keep working during Phase 1.
"""

from app.core.models import *  # noqa: F401,F403
