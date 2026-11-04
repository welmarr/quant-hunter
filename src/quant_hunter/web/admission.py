"""Count actual shared operational reservations, never scientific attempts.

Call inside BEGIN IMMEDIATE when deciding admission. A worker and its one
linked data operation occupy one slot; unlinked or orphaned operations still
count. Fixed table names support older runtimes before optional adapters exist.
"""

from __future__ import annotations

import sqlite3


def resource_counts(db: sqlite3.Connection) -> tuple[int, int]:
    """Return active work and total queued/reserved work under the caller's lock."""
    tables = {
        str(row[0])
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    active = queued = 0
    borrowed: set[str] = set()
    if "resource_readers" in tables:
        readers = int(db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0])
        active += readers
        queued += readers
    for table in ("data_operations", "publication_operations"):
        if table in tables:
            count = int(
                db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE status='RUNNING'"  # noqa: S608 -- fixed literal allowlist
                ).fetchone()[0]
            )
            active += count
            queued += count
    if "jobs" in tables:
        linked = "data_operations" in tables and any(
            row[1] == "worker_job_id"
            for row in db.execute("PRAGMA table_info(data_operations)")
        )
        if linked:
            rows = db.execute(
                "SELECT j.status,COUNT(*) FROM jobs j WHERE "
                "j.status IN ('QUEUED','RUNNING') AND NOT EXISTS "
                "(SELECT 1 FROM data_operations d WHERE d.status='RUNNING' "
                "AND d.worker_job_id=j.id AND d.owner_id=j.owner_id "
                "AND j.status='RUNNING') GROUP BY j.status"
            )
        else:
            rows = db.execute(
                "SELECT status,COUNT(*) FROM jobs WHERE status IN "
                "('QUEUED','RUNNING') GROUP BY status"
            )
        for status, count in rows:
            queued += int(count)
            if status == "RUNNING":
                active += int(count)
    if "paper_jobs" in tables:
        for status, count in db.execute(
            "SELECT status,COUNT(*) FROM paper_jobs WHERE status NOT IN "
            "('COMPLETED','FAILED','CANCELLED') GROUP BY status"
        ):
            queued += int(count)
            if status in ("STARTING", "STEPPING", "RECOVERING"):
                active += int(count)
    if {
        "resource_paper_links",
        "resource_readers",
        "paper_jobs",
        "qhp_halt_events",
    } <= tables:
        # A proof reader occupies an active slot while borrowing only its exact
        # still-paused task's existing queue reservation. Stale/orphan links do
        # not reduce the count. Native work never runs with this reader held.
        borrowed.update(
            str(row[0])
            for row in db.execute(
                "SELECT p.id FROM resource_paper_links l "
                "JOIN resource_readers r ON r.id=l.reader_id "
                "JOIN paper_jobs p ON p.id=l.paper_job_id "
                "JOIN qhp_halt_events h ON h.revision=l.halt_revision "
                "WHERE p.owner_id=l.paper_owner_id AND p.status='PAUSED' "
                "AND p.revision=l.workflow_revision AND h.digest=l.halt_digest "
                "AND h.revision=(SELECT MAX(revision) FROM qhp_halt_events) "
                "AND h.revision % 2 = 1"
            )
        )
    if {"resource_resume_links", "resource_readers", "paper_jobs"} <= tables:
        borrowed.update(
            str(row[0])
            for row in db.execute(
                "SELECT p.id FROM resource_resume_links l "
                "JOIN resource_readers r ON r.id=l.reader_id "
                "JOIN paper_jobs p ON p.id=l.paper_job_id "
                "WHERE p.owner_id=l.paper_owner_id AND r.owner_id=l.paper_owner_id "
                "AND p.status='PAUSED' AND p.revision=l.workflow_revision"
            )
        )
    return active, queued - len(borrowed)
