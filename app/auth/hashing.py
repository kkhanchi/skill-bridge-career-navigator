"""Argon2id password hashing (Phase 3).

Thin wrapper around `argon2.PasswordHasher` (the argon2id variant)
that:

- Reads cost parameters from the active Flask config at construction
  time so `TestConfig` can dial them down without touching prod
  defaults (ADR-012).
- Swallows `argon2` exceptions in `verify` so no library-internal
  exception surfaces at the handler layer (R10.4).
- Exposes a `dummy_hash` property — a valid argon2id encoded string
  produced at the same cost parameters — for the constant-time login
  flow (R2.4). Running `verify(dummy_hash, attempted_password)` on
  the unknown-email branch takes the same time as verifying a real
  user's password, closing the timing-based account-enumeration leak.

Design reference: `.kiro/specs/phase-3-auth/design.md` §Password hashing.
Requirement reference: R10.1, R10.4, R10.5.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)


# The payload content of the dummy is irrelevant — only its cost params
# and validity need to match the hasher's. A caller-supplied constant
# here keeps the dummy deterministic; a per-request re-hash would add
# ~50ms to every unknown-email login on production cost params.
_DUMMY_PASSWORD = "skill-bridge-dummy-password-for-constant-time-verify"


class Argon2Hasher:
    """Adapter over `argon2-cffi`'s `PasswordHasher`.

    Construct one per Flask app via `init_extensions`. The cost
    parameters are frozen on construction — changing them requires
    building a new hasher.
    """

    def __init__(
        self,
        *,
        time_cost: int,
        memory_cost: int,
        parallelism: int,
    ) -> None:
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
        )
        # Pre-compute the dummy hash at the same cost params so the
        # constant-time verify on the unknown-email branch takes
        # equivalent work. Cached as an instance attribute — never
        # re-derived.
        self._dummy_hash = self._hasher.hash(_DUMMY_PASSWORD)

    # ---- primary API ----------------------------------------------------

    def hash(self, password: str) -> str:
        """Return an argon2id encoded string for *password*.

        Precondition: Pydantic has already validated length (8..128)
        and non-whitespace-only. This method is not defensive against
        inputs that bypass the schema.
        """
        return self._hasher.hash(password)

    def verify(self, hashed: str, password: str) -> bool:
        """Return True iff *password* matches *hashed*.

        Catches the three argon2 exception families internally:

        - `VerifyMismatchError` — wrong password (the common case).
        - `VerificationError` — verification failed for a non-match
          reason (e.g. a well-formed hash that rejects every input).
        - `InvalidHashError` — the stored hash string is malformed
          or unparseable. Note: `InvalidHashError` descends from
          `ValueError`, NOT from `VerificationError`, so it must be
          listed explicitly.

        No argon2 exception propagates to handlers (R10.4) — a
        malformed stored hash surfaces the same way as a wrong
        password from the handler's perspective.
        """
        try:
            return self._hasher.verify(hashed, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    # ---- constant-time login support -----------------------------------

    @property
    def dummy_hash(self) -> str:
        """A valid argon2id hash at this instance's cost params.

        The login handler calls `hasher.verify(hasher.dummy_hash, pw)`
        on the unknown-email branch so that an attacker cannot
        distinguish "email not found" from "wrong password" via
        response timing (R2.4).
        """
        return self._dummy_hash
