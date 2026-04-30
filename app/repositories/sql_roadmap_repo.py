"""SQLAlchemy implementation of :class:`RoadmapRepository`.

The PATCH-a-resource handler is the interesting one:

- The target resource lives inside the ``phases`` JSON column.
- Mutating ``row.phases[i]["resources"][j]["completed"]`` in place
  does NOT automatically mark the column dirty — SQLAlchemy tracks
  column-level assignments, not nested dict mutations.
- ``flag_modified(row, "phases")`` is therefore mandatory; without
  it the mutation is silently dropped on commit, with no error,
  and the PATCH becomes a no-op on next read. This is the exact
  bug R7.1 + R7.3 exist to catch.

Phase 3 note: roadmaps have no ``user_id`` column — ownership is
carried transitively by the parent analysis's ``user_id``. The
``*_for_user`` methods JOIN through ``analyses`` to filter on
``analyses.user_id``.

Requirement reference: R2.1, R2.2, R7.1, R7.2, R7.3, R7.5, R12.1,
R12.3, R12.7.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import AnalysisORM, RoadmapORM
from app.db.session import get_db_session
from app.repositories._mappers import (
    roadmap_record_from_row,
    roadmap_row_from_record,
)
from app.repositories.base import RoadmapRecord


class SqlAlchemyRoadmapRepository:
    """Repository Protocol impl for roadmaps + resource updates."""

    # ---- Phase 1/2 methods ---------------------------------------------

    def create(self, record: RoadmapRecord) -> RoadmapRecord:
        session = get_db_session()
        row = roadmap_row_from_record(record)
        session.add(row)
        session.flush()
        # Round-trip through the mapper so the returned record has a
        # consistently-rebuilt resource_index, matching what
        # InMemoryRoadmapRepository.create produces.
        return roadmap_record_from_row(row)

    def get(self, roadmap_id: str) -> RoadmapRecord | None:
        session = get_db_session()
        row = session.get(RoadmapORM, roadmap_id)
        return roadmap_record_from_row(row) if row is not None else None

    def update_resource(
        self,
        roadmap_id: str,
        resource_id: str,
        completed: bool,
    ) -> RoadmapRecord | None:
        """Flip a resource's ``completed`` flag.

        Returns:
            The updated :class:`RoadmapRecord` on success, or ``None``
            when the roadmap is missing OR when the roadmap exists but
            the resource id isn't present. Handler disambiguates the
            two 404 codes by calling :meth:`get` afterwards, matching
            the Phase 1 contract.
        """
        session = get_db_session()
        row = session.get(RoadmapORM, roadmap_id)
        if row is None:
            return None

        # Walk the JSON phases to find the target resource. Short-circuit
        # on the first hit; resource ids are unique within a roadmap
        # (guaranteed by generate_roadmap).
        hit = False
        for phase in row.phases or []:
            for resource in phase.get("resources", []):
                if resource.get("id") == resource_id:
                    resource["completed"] = completed
                    hit = True
                    break
            if hit:
                break

        if not hit:
            # R7.5: don't mark the row dirty and don't bump updated_at —
            # the PATCH was a no-op targeting a non-existent resource.
            return None

        # R7.1 + R7.2: mandatory flag_modified call, plus explicit
        # updated_at bump so the returned record reflects the mutation.
        flag_modified(row, "phases")
        row.updated_at = datetime.now(UTC)
        session.flush()

        return roadmap_record_from_row(row)

    # ---- Phase 3 multi-tenant methods ----------------------------------

    def create_for_user(self, user_id: str, record: RoadmapRecord) -> RoadmapRecord:
        """Persist a roadmap owned (transitively) by ``user_id``.

        The ``user_id`` argument is retained for API symmetry across
        the three repositories. ``roadmaps`` itself has no ownership
        column, so the argument is unused at write time — ownership
        is derived via the referenced analysis's ``user_id``.
        """
        del user_id  # intentional: carried by roadmap.analysis_id's user
        return self.create(record)

    def get_for_user(self, roadmap_id: str, user_id: str) -> RoadmapRecord | None:
        """Fetch only when the owning analysis belongs to ``user_id``.

        JOINs roadmaps -> analyses and filters on analyses.user_id.
        Anti-enumeration (R12.7): wrong-owner is invisible.
        """
        session = get_db_session()
        row = session.scalar(
            select(RoadmapORM)
            .join(AnalysisORM, RoadmapORM.analysis_id == AnalysisORM.id)
            .where((RoadmapORM.id == roadmap_id) & (AnalysisORM.user_id == user_id))
        )
        return roadmap_record_from_row(row) if row is not None else None

    def update_resource_for_user(
        self,
        roadmap_id: str,
        resource_id: str,
        user_id: str,
        completed: bool,
    ) -> RoadmapRecord | None:
        """Update a resource only if the owning analysis belongs to ``user_id``.

        Ownership gate first; the mutation then reuses
        ``update_resource`` so the ``flag_modified("phases")``
        contract stays in one place. Two queries on the ownership
        path is an acceptable price for keeping the JSON-mutation
        invariant in a single method.
        """
        if self.get_for_user(roadmap_id, user_id) is None:
            return None
        return self.update_resource(roadmap_id, resource_id, completed)
