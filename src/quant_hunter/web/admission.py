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
    return active, queued
