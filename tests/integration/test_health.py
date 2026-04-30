"""Integration tests for the health endpoint + cross-cutting contract.

Validates R6.1 (error envelope), R6.5 (Flask HTTPException mapping),
R6.6 (envelope + correlation id on errors), R7.1/R7.2/R7.3
(correlation id generation, reuse, response header), R8.1/R8.3
(health endpoint shape + unversioned path).
"""

from __future__ import annotations


def test_health_returns_ok_and_correlation_header(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    # Correlation id is always emitted on every response, even trivial ones.
    assert "X-Correlation-ID" in response.headers
    assert response.headers["X-Correlation-ID"]  # non-empty


def test_health_echoes_inbound_correlation_id(client):
    response = client.get("/health", headers={"X-Correlation-ID": "abc-123"})

    assert response.status_code == 200
    # R7.2: an inbound X-Correlation-ID is reused on the response.
    assert response.headers["X-Correlation-ID"] == "abc-123"


def test_health_generates_correlation_id_when_absent(client):
    # Two requests without the header should get two distinct ids (R7.1).
    r1 = client.get("/health")
    r2 = client.get("/health")

    cid1 = r1.headers["X-Correlation-ID"]
    cid2 = r2.headers["X-Correlation-ID"]
    assert cid1 and cid2
    assert cid1 != cid2


def test_unknown_route_returns_error_envelope_with_correlation_id(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.get_json()
    # R6.1 / R6.6: body matches the Error_Envelope shape.
    assert isinstance(body, dict)
    assert set(body.keys()) == {"error"}
    assert isinstance(body["error"], dict)
    assert isinstance(body["error"].get("code"), str)
    assert isinstance(body["error"].get("message"), str)
    # R6.6: correlation id present on error responses too.
    assert response.headers["X-Correlation-ID"]


def test_health_rejects_unsupported_method(client):
    # R6.5: Flask HTTPException (405) is translated into the envelope shape.
    response = client.delete("/health")

    assert response.status_code == 405
    body = response.get_json()
    assert "error" in body
    assert body["error"]["code"]
    assert response.headers["X-Correlation-ID"]
