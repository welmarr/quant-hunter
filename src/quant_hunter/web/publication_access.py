"""Private operational ownership; PAPER revisions remain the document authority."""

from __future__ import annotations

import builtins
import secrets
import time
from collections.abc import Callable
from typing import cast

from quant_hunter.config import JsonRecord
from quant_hunter.identity import StaleWriterError
from quant_hunter.publications import PublicationError, PublicationService
from quant_hunter.web.admission import resource_counts
from quant_hunter.web.state import AccessError, AppState, User


class PublicationAccess:
    """Never infer ownership from a submitted PAPER or EXP identifier.

    A runtime lease must exclude prior workers before recover(). SQLite retains
    admissions and visibility, never document content or scientific decisions.
    """

    def __init__(
        self,
        state: AppState,
        service: PublicationService,
        *,
        capacity: Callable[[], None],
    ) -> None:
        self.state, self.service, self.capacity = state, service, capacity
        with state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS publication_ownership (
                    paper_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS publication_operations (
                    id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
                    kind TEXT NOT NULL, paper_id TEXT, created REAL NOT NULL,
                    status TEXT NOT NULL, revision_digest TEXT, error TEXT,
                    FOREIGN KEY(owner_id) REFERENCES users(id));
            """)

    def owns(self, user: User, paper_id: str) -> None:
        with self.state.connection() as db:
            if (
                db.execute(
                    "SELECT 1 FROM publication_ownership WHERE paper_id=? AND owner_id=?",
                    (paper_id, user.id),
                ).fetchone()
                is None
            ):
                raise AccessError("Publication is unavailable")

    def _links(self, user: User, reproduction: JsonRecord | None) -> None:
        if reproduction is None:
            return
        identifiers = reproduction.get("experiment_ids")
        if not isinstance(identifiers, list) or len(identifiers) > 64:
            raise AccessError("Invalid publication experiment links")
        with self.state.connection() as db:
            for identity in identifiers:
                if (
                    not isinstance(identity, str)
                    or db.execute(
                        "SELECT 1 FROM jobs WHERE owner_id=? AND experiment_id=? LIMIT 1",
                        (user.id, identity),
                    ).fetchone()
                    is None
                ):
                    raise AccessError("Linked experiment is unavailable")

    def _begin(self, user: User, kind: str, paper_id: str | None) -> str:
        if user.role not in ("owner", "researcher"):
            raise AccessError("Researcher role required")
        self.capacity()
        operation = secrets.token_hex(16)
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Admission and the cross-service count share the SQLite write lock.
            actor = db.execute(
                "SELECT role FROM users WHERE id=?", (user.id,)
            ).fetchone()
            if actor is None or actor[0] not in ("owner", "researcher"):
                raise AccessError("Researcher role required")
            active, queued = resource_counts(db)
            if active >= 2:
                raise AccessError("Resource operations busy; wait for completion")
            if queued >= 8:
                raise AccessError("Queue is full; wait for a job to finish")
            if (
                db.execute("SELECT COUNT(*) FROM publication_operations").fetchone()[0]
                >= 500
            ):
                raise AccessError(
                    "Publication operation quota reached; owner review required"
                )
            if (
                paper_id is not None
                and db.execute(
                    "SELECT 1 FROM publication_operations WHERE paper_id=? AND status='RUNNING'",
                    (paper_id,),
                ).fetchone()
            ):
                raise AccessError("Publication already has an active operation")
            db.execute(
                "INSERT INTO publication_operations VALUES(?,?,?,?,?,'RUNNING',NULL,NULL)",
                (operation, user.id, kind, paper_id, time.time()),
            )
        return operation

    def _finish(
        self,
        operation: str,
        *,
        result: JsonRecord | None = None,
        error: str | None = None,
        revision_digest: str | None = None,
        status: str | None = None,
        new_owner: User | None = None,
    ) -> None:
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            paper_id = result.get("paper_id") if result else None
            if result is not None:
                revision_digest = cast(str, result["revision_digest"])
            if new_owner is not None:
                if not isinstance(paper_id, str):
                    raise PublicationError("MISSING_CREATED_IDENTITY")
                db.execute(
                    "INSERT INTO publication_ownership VALUES(?,?)",
                    (paper_id, new_owner.id),
                )
            db.execute(
                "UPDATE publication_operations SET status=?,revision_digest=?,error=?,"
                "paper_id=COALESCE(?,paper_id) WHERE id=? AND status='RUNNING'",
                (
                    status or ("FAILED" if error else "SUCCEEDED"),
                    revision_digest,
                    error,
                    paper_id,
                    operation,
                ),
            )

    def _mutate(
        self,
        user: User,
        kind: str,
        paper_id: str | None,
        action: Callable[[], JsonRecord],
    ) -> JsonRecord:
        if paper_id is not None:
            self.get(user, paper_id)
        operation = self._begin(user, kind, paper_id)
        try:
            result = action()
            self._finish(
                operation, result=result, new_owner=user if paper_id is None else None
            )
            return result
        except Exception as error:
            code = (
                error.code
                if isinstance(error, PublicationError)
                else (
                    "STALE_REVISION"
                    if isinstance(error, StaleWriterError)
                    else "PUBLICATION_OPERATION_FAILED"
                )
            )
            self._finish(
                operation,
                error=code,
                revision_digest=error.revision_digest
                if isinstance(error, PublicationError)
                else None,
            )
            raise
        # BaseException/process loss leaves RUNNING; startup recovery never retries.

    def create(self, user: User, metadata: JsonRecord) -> JsonRecord:
        return self._mutate(user, "CREATE", None, lambda: self.service.create(metadata))

    def create_reference(
        self, user: User, *, doi: str | None = None, url: str | None = None
    ) -> JsonRecord:
        return self._mutate(
            user,
            "REFERENCE",
            None,
            lambda: self.service.create_reference(doi=doi, url=url),
        )

    def get(self, user: User, paper_id: str) -> JsonRecord:
        self.owns(user, paper_id)
        result = self.service.get(paper_id)
        self._links(user, cast(JsonRecord, result["reproduction"]))
        return result

    def text(self, user: User, paper_id: str) -> JsonRecord:
        self.get(user, paper_id)
        return self.service.get_text(paper_id)

    def list(self, user: User, *, limit: int = 25, offset: int = 0) -> list[JsonRecord]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or type(offset) is not int
            or not 0 <= offset <= 500
        ):
            raise AccessError("Invalid publication page")
        with self.state.connection() as db:
            identities = [
                str(r[0])
                for r in db.execute(
                    "SELECT paper_id FROM publication_ownership WHERE owner_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (user.id, limit, offset),
                )
            ]
        return [self.get(user, identity) for identity in identities]

    def operations(self, user: User) -> builtins.list[JsonRecord]:
        with self.state.connection() as db:
            return [
                cast(JsonRecord, dict(row))
                for row in db.execute(
                    "SELECT id,kind,paper_id,created,status,revision_digest,error FROM publication_operations "
                    "WHERE owner_id=? ORDER BY rowid DESC LIMIT 100",
                    (user.id,),
                )
            ]

    def update(
        self,
        user: User,
        paper_id: str,
        *,
        expected_digest: str,
        metadata: JsonRecord | None = None,
        dossier: JsonRecord | None = None,
        reading: JsonRecord | None = None,
        reproduction: JsonRecord | None = None,
    ) -> JsonRecord:
        self.owns(user, paper_id)
        self._links(user, reproduction)
        return self._mutate(
            user,
            "UPDATE",
            paper_id,
            lambda: self.service.update(
                paper_id,
                expected_digest=expected_digest,
                metadata=metadata,
                dossier=dossier,
                reading=reading,
                reproduction=reproduction,
            ),
        )

    def attach(
        self,
        user: User,
        paper_id: str,
        raw: bytes,
        *,
        expected_digest: str,
        media_type: str,
        declared_license: str,
    ) -> JsonRecord:
        return self._mutate(
            user,
            "ATTACH",
            paper_id,
            lambda: self.service.attach(
                paper_id,
                raw,
                expected_digest=expected_digest,
                media_type=media_type,
                declared_license=declared_license,
            ),
        )

    def extract(
        self,
        user: User,
        paper_id: str,
        *,
        expected_digest: str,
        page_start: int = 0,
        page_count: int = 50,
    ) -> JsonRecord:
        return self._mutate(
            user,
            "EXTRACT",
            paper_id,
            lambda: self.service.extract(
                paper_id,
                expected_digest=expected_digest,
                page_start=page_start,
                page_count=page_count,
            ),
        )

    def retrieve_metadata(
        self, user: User, paper_id: str, *, expected_digest: str
    ) -> JsonRecord:
        return self._mutate(
            user,
            "CROSSREF",
            paper_id,
            lambda: self.service.retrieve_metadata(
                paper_id, expected_digest=expected_digest
            ),
        )

    def fetch_primary(
        self,
        user: User,
        paper_id: str,
        url: str,
        *,
        expected_digest: str,
        declared_license: str,
    ) -> JsonRecord:
        return self._mutate(
            user,
            "FETCH",
            paper_id,
            lambda: self.service.fetch_primary(
                paper_id,
                url,
                expected_digest=expected_digest,
                declared_license=declared_license,
            ),
        )

    def recover(self) -> None:
        """Call only after acquiring the runtime lease, before serving requests."""
        with self.state.connection() as db:
            pending = list(
                db.execute(
                    "SELECT id,paper_id FROM publication_operations WHERE status='RUNNING'"
                )
            )
        for row in pending:
            try:
                result = None
                if row["paper_id"] is not None:
                    detail = self.service.get(str(row["paper_id"]))
                    result = self.service.recover_interrupted(
                        str(row["paper_id"]),
                        expected_digest=cast(str, detail["revision_digest"]),
                    )
                self._finish(
                    str(row["id"]),
                    result=result,
                    error="INTERRUPTED_NO_REPLAY",
                    status="INTERRUPTED",
                )
            except Exception:
                self._finish(
                    str(row["id"]),
                    error="RECOVERY_REQUIRES_REVIEW",
                    status="INTERRUPTED",
                )
