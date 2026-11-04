"""Owner account maintenance with retained history and session revocation."""

from __future__ import annotations

import secrets
import sqlite3
import time

from quant_hunter.web.state import AccessError, AppState, User, _password


class UserAdministration:
    def __init__(self, state: AppState) -> None:
        self.state = state
        with state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS user_admin_revisions (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id),
                    revision INTEGER NOT NULL CHECK(revision >= 0));
                CREATE TABLE IF NOT EXISTS user_admin_events (
                    sequence INTEGER PRIMARY KEY,
                    actor_id INTEGER NOT NULL REFERENCES users(id),
                    target_id INTEGER NOT NULL REFERENCES users(id),
                    revision INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    previous_role TEXT NOT NULL,
                    resulting_role TEXT NOT NULL,
                    revoked_sessions INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(target_id,revision));
            """)

    @staticmethod
    def _owner(db: sqlite3.Connection, actor: User) -> None:
        actual = db.execute(
            "SELECT username,role FROM users WHERE id=?", (actor.id,)
        ).fetchone()
        if (
            actual is None
            or tuple(actual) != (actor.username, "owner")
            or actor.role != "owner"
        ):
            raise AccessError("Owner account administration required")

    def accounts(
        self, actor: User, *, after: int = 0, limit: int = 25
    ) -> list[dict[str, object]]:
        if (
            type(after) is not int
            or not 0 <= after <= 9223372036854775807
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise AccessError("Invalid account page")
        with self.state.connection() as db:
            self._owner(db, actor)
            return [
                dict(row)
                for row in db.execute(
                    "SELECT u.id,u.username,u.role,COALESCE(r.revision,0) AS revision "
                    "FROM users u LEFT JOIN user_admin_revisions r ON r.user_id=u.id WHERE u.id>? ORDER BY u.id LIMIT ?",
                    (after, limit),
                )
            ]

    def change(
        self,
        actor: User,
        target_id: int,
        *,
        expected_revision: int,
        action: str,
        role: str | None = None,
        password: str | None = None,
    ) -> dict[str, object]:
        if (
            type(target_id) is not int
            or not 1 <= target_id <= 9223372036854775807
            or type(expected_revision) is not int
            or not 0 <= expected_revision < 10000
        ):
            raise AccessError("Invalid account revision")
        if action == "ROLE":
            valid = role in {"owner", "researcher", "reader"} and password is None
        elif action == "PASSWORD":
            valid = (
                role is None
                and isinstance(password, str)
                and 12 <= len(password) <= 128
            )
        elif action == "REVOKE_SESSIONS":
            valid = role is None and password is None
        else:
            valid = False
        if not valid:
            raise AccessError("Invalid closed account change")
        with self.state.connection() as db:
            self._owner(db, actor)
        salt = secrets.token_hex(16) if action == "PASSWORD" else None
        encoded = (
            _password(password, salt)
            if password is not None and salt is not None
            else None
        )
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owner(db, actor)
            target = db.execute(
                "SELECT u.id,u.username,u.role,COALESCE(r.revision,0) AS revision "
                "FROM users u LEFT JOIN user_admin_revisions r ON r.user_id=u.id WHERE u.id=?",
                (target_id,),
            ).fetchone()
            if target is None or target["revision"] != expected_revision:
                raise AccessError("Account revision changed; refresh accounts")
            if (
                db.execute("SELECT COUNT(*) FROM user_admin_events").fetchone()[0]
                >= 10000
            ):
                raise AccessError("Account audit capacity reached; retain history")
            resulting_role = role if action == "ROLE" else target["role"]
            if (
                target["role"] == "owner"
                and resulting_role != "owner"
                and db.execute(
                    "SELECT COUNT(*) FROM users WHERE role='owner'"
                ).fetchone()[0]
                <= 1
            ):
                raise AccessError("The last owner must remain an owner")
            if action == "ROLE":
                db.execute("UPDATE users SET role=? WHERE id=?", (role, target_id))
            elif action == "PASSWORD":
                db.execute(
                    "UPDATE users SET salt=?,password_hash=? WHERE id=?",
                    (salt, encoded, target_id),
                )
                db.execute(
                    "DELETE FROM login_attempts WHERE username=?", (target["username"],)
                )
            revoked = db.execute(
                "DELETE FROM sessions WHERE user_id=?", (target_id,)
            ).rowcount
            revision = expected_revision + 1
            db.execute(
                "INSERT INTO user_admin_revisions VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision",
                (target_id, revision),
            )
            db.execute(
                "INSERT INTO user_admin_events(actor_id,target_id,revision,action,previous_role,resulting_role,revoked_sessions,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    actor.id,
                    target_id,
                    revision,
                    action,
                    target["role"],
                    resulting_role,
                    revoked,
                    time.time(),
                ),
            )
            return {
                "id": target_id,
                "username": target["username"],
                "role": resulting_role,
                "revision": revision,
                "action": action,
                "revoked_sessions": revoked,
            }

    def history(
        self, actor: User, *, after: int = 0, limit: int = 25
    ) -> list[dict[str, object]]:
        if (
            type(after) is not int
            or not 0 <= after <= 10000
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise AccessError("Invalid account audit page")
        with self.state.connection() as db:
            self._owner(db, actor)
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM user_admin_events WHERE sequence>? ORDER BY sequence LIMIT ?",
                    (after, limit),
                )
            ]
