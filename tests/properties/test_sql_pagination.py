"""SQL-backend pagination partition property (R8.4).

Mirrors the Phase 1 R3.7 property but against the SQL backend: for
any (keyword, skill, limit) triple, concatenating every page at the
given limit equals the full filtered list with no duplicates, and
``meta.total`` is invariant across pages.

Property 4: SQL pagination partition — Validates R8.4.
"""

from __future__ import annotations

from math import ceil

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import integers, just, one_of, sampled_from

from app import create_app
from app.db.base import Base
from app.db.models import JobORM


_SEEDED_JOB_COUNT = 25  # module-scope catalog size


def _build_app():
    """Build a SQL app with a fixed 25-row jobs catalog."""
    app = create_app("test_sql")
    ext = app.extensions["skillbridge"]
    with app.app_context():
        Base.metadata.create_all(ext.engine)
        with ext.session_factory() as session:
            for i in range(_SEEDED_JOB_COUNT):
                session.add(JobORM(
                    id=f"j-{i:03d}",
                    title=f"Role {i}",
                    description=f"desc {i}",
                    required_skills=["Python"] if i % 2 == 0 else ["Java"],
                    preferred_skills=["Docker"] if i % 3 == 0 else [],
                    experience_level="Mid",
                ))
            session.commit()
    return app


# Strategies for filters. Keep the alphabet small so Hypothesis can
# reach interesting combinations without generating hundreds of
# throwaway requests.
_keyword = one_of(
    just(""),
    sampled_from(["Role", "Role 1", "nonexistent", "desc"]),
)
_skill = one_of(
    just(""),
    sampled_from(["Python", "Java", "Docker", "nonexistent-skill"]),
)
_limit = integers(min_value=1, max_value=30)


@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(keyword=_keyword, skill=_skill, limit=_limit)
def test_pagination_partition_property(keyword, skill, limit):
    app = _build_app()
    client = app.test_client()

    # Reference: single large-limit call with the same filters.
    ref = client.get(
        f"/api/v1/jobs?keyword={keyword}&skill={skill}&limit=100&page=1"
    )
    assert ref.status_code == 200
    reference_items = ref.get_json()["items"]
    expected_total = len(reference_items)
    expected_pages = ceil(expected_total / limit) if expected_total > 0 else 0

    # Walk every page at the given limit, concatenate items.
    concatenated: list[dict] = []
    totals_seen: set[int] = set()
    page_counts_seen: set[int] = set()

    for page in range(1, max(expected_pages, 1) + 1):
        r = client.get(
            f"/api/v1/jobs?keyword={keyword}&skill={skill}&limit={limit}&page={page}"
        )
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        concatenated.extend(body["items"])
        totals_seen.add(body["meta"]["total"])
        page_counts_seen.add(body["meta"]["pages"])

    # total invariant across pages
    assert totals_seen == {expected_total}
    # pages invariant across pages and matches ceil(total/limit)
    assert page_counts_seen == {expected_pages}
    # Concatenation equals reference (same order, same items).
    assert [item["id"] for item in concatenated] == [
        item["id"] for item in reference_items
    ]
    # No duplicates across pages.
    ids = [item["id"] for item in concatenated]
    assert len(set(ids)) == len(ids)
