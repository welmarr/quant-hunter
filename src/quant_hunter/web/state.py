"""SQLite users, sessions and recoverable jobs; never a scientific ledger."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

Role = Literal["owner", "researcher", "reader"]


class AccessError(ValueError):
    """A local application authorization or state check failed."""


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: Role


@dataclass(frozen=True)
class Session:
    user: User
    csrf: str


@dataclass(frozen=True)
class Job:
    id: str
    owner_id: int
    status: str
    config: dict[str, str | int]
    experiment_id: str | None
    error: str | None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _password(password: str, salt: str) -> str:
    return hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    ).hex()


class AppState:
    """Short explicit transactions keep operational ownership checks atomic."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS migrations (version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO migrations VALUES (1);
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL CHECK(role IN ('owner','researcher','reader')),
                    salt TEXT NOT NULL, password_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    csrf TEXT NOT NULL, expires REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS login_attempts (
                    username TEXT PRIMARY KEY, count INTEGER NOT NULL, since REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, status TEXT NOT NULL,
                    config TEXT NOT NULL, experiment_id TEXT, error TEXT,
                    FOREIGN KEY(owner_id) REFERENCES users(id));
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def needs_owner(self) -> bool:
        with self.connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0]) == 0

    def create_user(
        self, username: str, password: str, role: Role, *, bootstrap: bool
    ) -> User:
        if role not in ("owner", "researcher", "reader"):
            raise AccessError("Invalid role")
        salt = secrets.token_hex(16)
        password_hash = _password(password, salt)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if bootstrap and (
                role != "owner" or db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            ):
                raise AccessError("Owner already configured")
            try:
                cursor = db.execute(
                    "INSERT INTO users(username,role,salt,password_hash) VALUES(?,?,?,?)",
                    (username, role, salt, password_hash),
                )
            except sqlite3.IntegrityError as exc:
                raise AccessError("Username is unavailable") from exc
            return User(cast(int, cursor.lastrowid), username, role)

    def login(self, username: str, password: str) -> tuple[str, Session]:
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute(
                "SELECT count,since FROM login_attempts WHERE username=?", (username,)
            ).fetchone()
            if attempt and attempt[0] >= 5 and now - attempt[1] < 60:
                raise AccessError("Login temporarily limited; retry after one minute")
            row = db.execute(
                "SELECT * FROM users WHERE username=?", (username,)
            ).fetchone()
            salt = str(row["salt"]) if row else "00" * 16
            expected = str(row["password_hash"]) if row else "00" * 64
            valid = hmac.compare_digest(_password(password, salt), expected)
            if not valid or row is None:
                count = int(attempt[0]) + 1 if attempt and now - attempt[1] < 60 else 1
                since = float(attempt[1]) if attempt and now - attempt[1] < 60 else now
                db.execute(
                    "INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)",
                    (username, count, since),
                )
                db.commit()  # Retain failures even though authentication raises.
                raise AccessError("Invalid username or password")
            db.execute("DELETE FROM login_attempts WHERE username=?", (username,))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?,?)",
                (_digest(token), row["id"], csrf, now + 28800),
            )
            return token, Session(User(row["id"], row["username"], row["role"]), csrf)

    def session(self, token: str) -> Session:
        with self.connection() as db:
            row = db.execute(
                "SELECT u.id,u.username,u.role,s.csrf FROM sessions s JOIN users u "
                "ON s.user_id=u.id WHERE s.token_hash=? AND s.expires>?",
                (_digest(token), time.time()),
            ).fetchone()
        if row is None:
            raise AccessError("Sign in to continue")
        return Session(User(row["id"], row["username"], row["role"]), row["csrf"])

    def logout(self, token: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (_digest(token),))

    def users(self) -> list[User]:
        with self.connection() as db:
            return [
                User(r["id"], r["username"], r["role"])
                for r in db.execute("SELECT id,username,role FROM users ORDER BY id")
            ]

    def enqueue(self, user: User, config: dict[str, str | int]) -> Job:
        if user.role not in ("owner", "researcher"):
            raise AccessError("Researcher role required")
        job_id = secrets.token_hex(16)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')"
            ).fetchone()[0]
            if pending >= 8:
                raise AccessError("Queue is full; wait for a job to finish")
            db.execute(
                "INSERT INTO jobs VALUES(?,?,'QUEUED',?,NULL,NULL)",
                (job_id, user.id, json.dumps(config, sort_keys=True)),
            )
        return Job(job_id, user.id, "QUEUED", config, None, None)

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            row["id"],
            row["owner_id"],
            row["status"],
            json.loads(row["config"]),
            row["experiment_id"],
            row["error"],
        )

    def jobs(self, user: User) -> list[Job]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE owner_id=? ORDER BY rowid DESC", (user.id,)
            )
            return [self._job(r) for r in rows]

    def job(self, user: User, job_id: str) -> Job:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE id=? AND owner_id=?", (job_id, user.id)
            ).fetchone()
        if row is None:
            raise AccessError("Job is unavailable")
        return self._job(row)

    def claim(self) -> Job | None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status='QUEUED' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='RUNNING' WHERE id=?", (row["id"],))
            return Job(
                row["id"],
                row["owner_id"],
                "RUNNING",
                json.loads(row["config"]),
                None,
                None,
            )

    def bind(self, job_id: str, experiment_id: str) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET experiment_id=? WHERE id=? AND status='RUNNING'",
                (experiment_id, job_id),
            )

    def finish(self, job_id: str, *, error: str | None = None) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET status=?,error=? WHERE id=? AND status='RUNNING'",
                ("FAILED" if error else "SUCCEEDED", error, job_id),
            )

    def cancel(self, user: User, job_id: str) -> None:
        with self.connection() as db:
            updated = db.execute(
                "UPDATE jobs SET status='CANCELLED' WHERE id=? AND owner_id=? AND status='QUEUED'",
                (job_id, user.id),
            ).rowcount
        if updated != 1:
            raise AccessError("Only your queued jobs can be cancelled")

    def interrupted(self) -> list[Job]:
        with self.connection() as db:
            return [
                self._job(r)
                for r in db.execute("SELECT * FROM jobs WHERE status='RUNNING'")
            ]
