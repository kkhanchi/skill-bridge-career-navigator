"""Request validation decorators built on Pydantic v2.

Two decorators: ``@validate_body`` for JSON request bodies and
``@validate_query`` for querystring parameters. Both parse the raw input
through a Pydantic model and inject the parsed instance as a keyword
argument. Failures surface as :class:`ApiError` with code
``VALIDATION_FAILED`` (HTTP 400) and the Pydantic error list in
``details.errors`` — preserving the Error_Envelope contract (R6.1, R6.3).

Design reference: `.kiro/specs/phase-1-rest-api/design.md` §Validation.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from flask import request
from pydantic import BaseModel, ValidationError

from app.utils.errors import VALIDATION_FAILED, ApiError

F = TypeVar("F", bound=Callable[..., Any])


def _raise_validation_error(err: ValidationError) -> None:
    raise ApiError(
        code=VALIDATION_FAILED,
        message="Request validation failed",
        status=400,
        details={"errors": err.errors(include_url=False)},
    )


def validate_body(model: type[BaseModel]) -> Callable[[F], F]:
    """Parse ``request.get_json()`` through *model* and inject as ``body=``.

    A missing / non-JSON body is treated as ``{}``. If that fails the
    model's required-field checks, Pydantic raises ValidationError and
    we convert it to ApiError 400. This also handles malformed JSON —
    ``silent=True`` returns ``None`` for unparseable bodies, which then
    fails validation with a clean error message rather than a Werkzeug
    BadRequest.
    """

    def wrap(fn: F) -> F:
        @functools.wraps(fn)
        def inner(*args: Any, **kwargs: Any) -> Any:
            payload = request.get_json(silent=True)
            if payload is None:
                payload = {}
            try:
                parsed = model.model_validate(payload)
            except ValidationError as err:
                _raise_validation_error(err)
            return fn(*args, body=parsed, **kwargs)

        return inner  # type: ignore[return-value]

    return wrap


def validate_query(model: type[BaseModel]) -> Callable[[F], F]:
    """Parse ``request.args`` through *model* and inject as ``query=``.

    Query parameters arrive as strings; Pydantic's coercion handles the
    common cases (int for ``page``/``limit``, str for ``keyword``/``skill``).
    """

    def wrap(fn: F) -> F:
        @functools.wraps(fn)
        def inner(*args: Any, **kwargs: Any) -> Any:
            raw = request.args.to_dict(flat=True)
            try:
                parsed = model.model_validate(raw)
            except ValidationError as err:
                _raise_validation_error(err)
            return fn(*args, query=parsed, **kwargs)

        return inner  # type: ignore[return-value]

    return wrap
