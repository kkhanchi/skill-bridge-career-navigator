"""Unit tests for Argon2Hasher.

Runs against the TestConfig weakened cost params (time_cost=1,
memory_cost=8 KiB, parallelism=1) so the Hypothesis property test
stays under a few seconds even with max_examples=15.

Requirement reference: R10.1, R10.4, R10.5.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import text

from app.auth.hashing import Argon2Hasher


def _fresh_hasher() -> Argon2Hasher:
    """Build a hasher with the same weak TestConfig params."""
    return Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1)


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------


def test_verify_accepts_matching_password():
    hasher = _fresh_hasher()
    h = hasher.hash("correct horse battery staple")
    assert hasher.verify(h, "correct horse battery staple") is True


def test_verify_rejects_different_password():
    hasher = _fresh_hasher()
    h = hasher.hash("correct horse battery staple")
    assert hasher.verify(h, "wrong password") is False


def test_verify_handles_malformed_hash_without_raising():
    # R10.4: no argon2 exception propagates — a garbage stored hash
    # surfaces as False, same as a wrong password would.
    hasher = _fresh_hasher()
    assert hasher.verify("not a valid argon2 hash", "any password") is False


def test_verify_handles_empty_hash_without_raising():
    hasher = _fresh_hasher()
    assert hasher.verify("", "any password") is False


def test_hash_produces_argon2id_encoded_string():
    # Sanity: argon2id hashes start with `$argon2id$`.
    hasher = _fresh_hasher()
    h = hasher.hash("some-valid-password")
    assert h.startswith("$argon2id$")


def test_same_password_produces_different_hashes():
    # argon2 includes a random salt per hash, so repeated hashes of
    # the same password differ. Both still verify.
    hasher = _fresh_hasher()
    h1 = hasher.hash("same-password")
    h2 = hasher.hash("same-password")
    assert h1 != h2
    assert hasher.verify(h1, "same-password") is True
    assert hasher.verify(h2, "same-password") is True


# ---------------------------------------------------------------------------
# DUMMY_HASH / constant-time support
# ---------------------------------------------------------------------------


def test_dummy_hash_is_a_valid_argon2id_hash():
    hasher = _fresh_hasher()
    # Verifying a random password against the dummy must return False
    # without raising (same contract as any real verify).
    assert hasher.dummy_hash.startswith("$argon2id$")
    assert hasher.verify(hasher.dummy_hash, "random-attempt") is False


def test_dummy_hash_matches_hasher_cost_params():
    # The dummy's encoded params must match the hasher's config so
    # the constant-time verify on the unknown-email branch does the
    # same work as a real verify. argon2 encodes m= (memory_cost) and
    # t= (time_cost) in the hash string.
    hasher = Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1)
    # e.g. $argon2id$v=19$m=8,t=1,p=1$<salt>$<hash>
    assert "m=8,t=1,p=1" in hasher.dummy_hash


def test_dummy_hash_is_stable_per_instance():
    # Cached as an attribute — the same instance always returns the
    # same dummy string.
    hasher = _fresh_hasher()
    assert hasher.dummy_hash == hasher.dummy_hash


# ---------------------------------------------------------------------------
# Property: hash round-trip determinism (R10.5)
# ---------------------------------------------------------------------------


# Valid-password strategy: 8..128 chars, non-whitespace-only, arbitrary
# text. Hypothesis still tries surprising unicode under this strategy,
# which is a useful stress on argon2's byte-encoding path.
_valid_password = text(
    min_size=8,
    max_size=128,
).filter(lambda s: s.strip() != "")


@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(password=_valid_password)
def test_hash_round_trip_property(password):
    """FOR ALL valid passwords p, verify(hash(p), p) is True."""
    hasher = _fresh_hasher()
    hashed = hasher.hash(password)
    assert hasher.verify(hashed, password) is True


@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(password=_valid_password, wrong=text(min_size=1, max_size=20))
def test_hash_rejects_wrong_password_property(password, wrong):
    """FOR ALL (p, q) with p != q, verify(hash(p), q) is False."""
    if wrong == password:
        # Edge case: Hypothesis happened to pick the same string. Skip
        # — not a meaningful failure, and filtering in the strategy
        # itself is more expensive than this one assertion.
        pytest.skip("collision")
    hasher = _fresh_hasher()
    hashed = hasher.hash(password)
    assert hasher.verify(hashed, wrong) is False
