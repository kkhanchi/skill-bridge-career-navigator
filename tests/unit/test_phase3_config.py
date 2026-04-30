"""Unit tests for Phase 3 config + error-code extensions.

Requirement reference: R9.1, R9.2, R9.3, R9.5, R10.2, R10.3, R13.5,
R14.2.
"""

from __future__ import annotations

from app import utils
from app.config import BaseConfig, DevConfig, ProdConfig, TestConfig, TestSqlConfig
from app.utils import errors as errors_module


# ---------------------------------------------------------------------------
# JWT_SECRET + TTL defaults
# ---------------------------------------------------------------------------


def test_test_config_has_fixed_jwt_secret():
    # R9.3: fixed literal so test runs observe stable signing behavior.
    assert TestConfig.JWT_SECRET == "test-secret-literal"


def test_test_sql_config_mirrors_test_config_auth_fields():
    # TestSqlConfig inherits the weakened argon2 + fixed JWT_SECRET.
    assert TestSqlConfig.JWT_SECRET == "test-secret-literal"


def test_dev_config_has_dev_jwt_secret_default():
    # R9.2: dev has a literal default so `python run.py` works without
    # env setup. The app factory will emit a warning when this is in
    # effect (wired in Stage J task 57).
    assert DevConfig.JWT_SECRET  # non-empty
    assert "do-not-use-in-prod" in DevConfig.JWT_SECRET


def test_prod_config_has_no_jwt_secret_class_default():
    # R9.1: ProdConfig does not override JWT_SECRET; it inherits
    # BaseConfig's env read which returns "" when unset. The app
    # factory raises RuntimeError at startup in that case (wired in
    # Stage J task 57).
    assert "JWT_SECRET" not in vars(ProdConfig)


def test_ttl_defaults():
    # R9.5: 15 min access, 14 days refresh.
    assert BaseConfig.ACCESS_TTL_SECONDS == 900
    assert BaseConfig.REFRESH_TTL_SECONDS == 1_209_600


# ---------------------------------------------------------------------------
# Argon2 cost parameters
# ---------------------------------------------------------------------------


def test_base_config_has_production_argon2_params():
    # R10.2: OWASP-recommended defaults on BaseConfig (inherited by
    # Dev and Prod).
    assert BaseConfig.ARGON2_TIME_COST == 2
    assert BaseConfig.ARGON2_MEMORY_COST == 65536
    assert BaseConfig.ARGON2_PARALLELISM == 4


def test_test_config_weakens_argon2_params():
    # R10.3: weakened for test speed — NEVER for prod.
    assert TestConfig.ARGON2_TIME_COST == 1
    assert TestConfig.ARGON2_MEMORY_COST == 8
    assert TestConfig.ARGON2_PARALLELISM == 1


def test_test_sql_config_weakens_argon2_params():
    assert TestSqlConfig.ARGON2_TIME_COST == 1
    assert TestSqlConfig.ARGON2_MEMORY_COST == 8
    assert TestSqlConfig.ARGON2_PARALLELISM == 1


# ---------------------------------------------------------------------------
# CORS_ORIGINS per-env
# ---------------------------------------------------------------------------


def test_dev_config_defaults_cors_to_wildcard():
    # R13.5: permissive for local SPA dev.
    assert DevConfig.CORS_ORIGINS == "*"


def test_test_config_disables_cors():
    # R13.5: tests assert on handler behavior, not CORS headers.
    assert TestConfig.CORS_ORIGINS == ""


def test_prod_config_has_no_cors_default():
    # R13.5: prod requires explicit opt-in via env.
    assert "CORS_ORIGINS" not in vars(ProdConfig)


# ---------------------------------------------------------------------------
# Error codes — the 6 new Phase 3 constants must exist on the errors module
# ---------------------------------------------------------------------------


def test_phase_3_error_codes_exported():
    # R14.2: closed set extended by exactly these six.
    assert errors_module.AUTH_REQUIRED == "AUTH_REQUIRED"
    assert errors_module.INVALID_CREDENTIALS == "INVALID_CREDENTIALS"
    assert errors_module.TOKEN_EXPIRED == "TOKEN_EXPIRED"
    assert errors_module.TOKEN_INVALID == "TOKEN_INVALID"
    assert errors_module.EMAIL_TAKEN == "EMAIL_TAKEN"
    assert errors_module.RATE_LIMITED == "RATE_LIMITED"


def test_phase_1_2_error_codes_still_present():
    # Regression: Phase 1/2 codes must not have been removed.
    assert errors_module.VALIDATION_FAILED == "VALIDATION_FAILED"
    assert errors_module.NOT_FOUND == "NOT_FOUND"
    assert errors_module.INTERNAL_ERROR == "INTERNAL_ERROR"
