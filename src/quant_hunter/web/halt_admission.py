"""Shared admission for a verified persistent local-paper protection task."""

from __future__ import annotations

import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager

from quant_hunter.web.admission import resource_counts
from quant_hunter.web.paper_access import PaperAccess, PaperConflictError
from quant_hunter.web.paper_halt import GlobalPaperHalt, halted, proof_lock
from quant_hunter.web.state import ResourceBusyError, User


class HaltReadAdmission:
    """Borrow one existing paper reservation without exceeding active capacity.

    The caller's immutable HALT task, actual actor and exact paused workflow are
    verified under the admission transaction. This is not general read access.
    """

    def __init__(self, halt: GlobalPaperHalt) -> None:
        self.halt, self.state = halt, halt.state
        with self.state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS resource_paper_links (
                    reader_id TEXT PRIMARY KEY REFERENCES resource_readers(id) ON DELETE CASCADE,
                    paper_job_id TEXT UNIQUE NOT NULL REFERENCES paper_jobs(id),
                    halt_revision INTEGER NOT NULL REFERENCES qhp_halt_events(revision),
                    paper_owner_id INTEGER NOT NULL REFERENCES users(id),
                    workflow_revision INTEGER NOT NULL,
                    halt_digest TEXT NOT NULL);
            """)

    @contextmanager
    def inspection(
        self, actor: User, paper_id: str, halt_revision: int
    ) -> Iterator[None]:
        identity = secrets.token_hex(16)
        # A protective control may queue during a native bar, but cannot alter
        # the exact paused reservation while its linked proof is being read.
        with proof_lock(self.state.path):
            with self.state.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                binding = self.halt.authorize_reader(db, actor, paper_id, halt_revision)
                active, queued = resource_counts(db)
                if active >= 2 or queued > 8:
                    raise ResourceBusyError("Paper protection read resources busy")
                if db.execute(
                    "SELECT 1 FROM resource_paper_links WHERE paper_job_id=?",
                    (paper_id,),
                ).fetchone():
                    raise ResourceBusyError("Paper protection read already reserved")
                resume_table = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='resource_resume_links'"
                ).fetchone()
                if (
                    resume_table
                    and db.execute(
                        "SELECT 1 FROM resource_resume_links WHERE paper_job_id=?",
                        (paper_id,),
                    ).fetchone()
                ):
                    raise ResourceBusyError("Paper resume read already reserved")
                db.execute(
                    "INSERT INTO resource_readers(id,owner_id,created) VALUES(?,?,?)",
                    (identity, actor.id, time.time()),
                )
                db.execute(
                    "INSERT INTO resource_paper_links VALUES(?,?,?,?,?,?)",
                    (
                        identity,
                        paper_id,
                        halt_revision,
                        binding["paper_owner_id"],
                        binding["workflow_revision"],
                        binding["halt_digest"],
                    ),
                )
                after_active, after_queued = resource_counts(db)
                if (
                    after_active != active + 1
                    or after_queued != queued
                    or after_queued > 8
                ):
                    raise ResourceBusyError(
                        "Paper protection reservation failed binding"
                    )
            try:
                yield
            finally:
                with self.state.connection() as db:
                    db.execute("DELETE FROM resource_readers WHERE id=?", (identity,))


class ResumeReadAdmission:
    """Owned paused-session provenance read; released before RESUME mutates state."""

    def __init__(self, paper: PaperAccess) -> None:
        self.paper, self.state = paper, paper.state
        with self.state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS resource_resume_links (
                    reader_id TEXT PRIMARY KEY REFERENCES resource_readers(id) ON DELETE CASCADE,
                    paper_job_id TEXT UNIQUE NOT NULL REFERENCES paper_jobs(id),
                    paper_owner_id INTEGER NOT NULL REFERENCES users(id),
                    workflow_revision INTEGER NOT NULL);
            """)

    @contextmanager
    def inspection(
        self, actor: User, paper_id: str, expected_revision: int
    ) -> Iterator[None]:
        identity = secrets.token_hex(16)
        with proof_lock(self.state.path):
            with self.state.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                self.paper._actor(db, actor, mutation=True)
                row = self.paper._load(db, paper_id, actor.id)
                if (
                    type(expected_revision) is not int
                    or row["revision"] != expected_revision
                    or row["status"] != "PAUSED"
                    or row["experiment_id"] is None
                    or row["inflight"] is not None
                    or row["requested"] is not None
                    or halted(db)
                ):
                    raise PaperConflictError("PAUSED_RESUME_RESERVATION_REQUIRED")
                active, queued = resource_counts(db)
                if active >= 2 or queued > 8:
                    raise ResourceBusyError("Paper resume inspection busy")
                if (
                    db.execute(
                        "SELECT 1 FROM resource_resume_links WHERE paper_job_id=?",
                        (paper_id,),
                    ).fetchone()
                    or db.execute(
                        "SELECT 1 FROM resource_paper_links WHERE paper_job_id=?",
                        (paper_id,),
                    ).fetchone()
                ):
                    raise ResourceBusyError("Paper read already reserved")
                db.execute(
                    "INSERT INTO resource_readers VALUES(?,?,?)",
                    (identity, actor.id, time.time()),
                )
                db.execute(
                    "INSERT INTO resource_resume_links VALUES(?,?,?,?)",
                    (identity, paper_id, actor.id, expected_revision),
                )
                if resource_counts(db) != (active + 1, queued):
                    raise ResourceBusyError("Paper resume reservation failed binding")
            try:
                yield
            finally:
                with self.state.connection() as db:
                    db.execute("DELETE FROM resource_readers WHERE id=?", (identity,))
