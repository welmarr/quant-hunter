"""Actual SQLite account maintenance oracles against the production module."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import TypedDict

import pytest

from quant_hunter.web import user_admin as module
from quant_hunter.web.state import AccessError, AppState, User

type Case = tuple[AppState, User, User, module.UserAdministration]


class ChangeFields(TypedDict, total=False):
    role: str
    password: str


class PageFields(TypedDict, total=False):
    after: int
    limit: int


@pytest.fixture
def case(tmp_path: Path) -> Case:
    state = AppState(tmp_path / "application.sqlite3")
    owner = state.create_user(
        "owner", "only-synthetic-owner-pass", "owner", bootstrap=True
    )
    reader = state.create_user(
        "reader", "only-synthetic-reader-pass", "reader", bootstrap=False
    )
    return state, owner, reader, module.UserAdministration(state)


def test_password_and_roles_revoke_old_sessions_keep_ownership_and_no_secret(
    case: Case,
) -> None:
    state, owner, reader, access = case
    old, _ = state.login(reader.username, "only-synthetic-reader-pass")
    change = access.change(
        owner, reader.id, expected_revision=0, action="ROLE", role="researcher"
    )
    assert change["revoked_sessions"] == 1
    with pytest.raises(AccessError):
        state.session(old)
    token, fresh = state.login(reader.username, "only-synthetic-reader-pass")
    assert fresh.user.role == "researcher" and fresh.user.id == reader.id
    access.change(
        owner,
        reader.id,
        expected_revision=1,
        action="PASSWORD",
        password="changed-synthetic-password",  # noqa: S106 -- synthetic test only
    )
    with pytest.raises(AccessError):
        state.session(token)
    with pytest.raises(AccessError):
        state.login(reader.username, "only-synthetic-reader-pass")
    _, fresh = state.login(reader.username, "changed-synthetic-password")
    assert fresh.user.id == reader.id
    history = access.history(owner)
    assert [item["action"] for item in history] == ["ROLE", "PASSWORD"]
    assert "password_hash" not in str(
        history
    ) and "changed-synthetic-password" not in str(history)
    with state.connection() as db:
        assert len(list(db.execute("PRAGMA foreign_key_check"))) == 0


def test_last_owner_and_stale_actor_cannot_administrate(case: Case) -> None:
    _state, owner, reader, access = case
    with pytest.raises(AccessError, match="last owner"):
        access.change(
            owner, owner.id, expected_revision=0, action="ROLE", role="reader"
        )
    access.change(owner, reader.id, expected_revision=0, action="ROLE", role="owner")
    second = replace(reader, role="owner")
    access.change(second, owner.id, expected_revision=0, action="ROLE", role="reader")
    with pytest.raises(AccessError):
        access.change(
            owner,
            second.id,
            expected_revision=1,
            action="PASSWORD",
            password="synthetic-password-change",  # noqa: S106 -- synthetic test only
        )
    with pytest.raises(AccessError):
        access.accounts(owner)
    assert len(access.history(second)) == 2


def test_actual_concurrent_revision_retains_one_change(case: Case) -> None:
    _state, owner, reader, access = case

    def invoke(role: str) -> dict[str, object] | None:
        try:
            return access.change(
                owner, reader.id, expected_revision=0, action="ROLE", role=role
            )
        except AccessError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, ["owner", "researcher"]))
    assert sum(item is not None for item in results) == 1
    assert len(access.history(owner)) == 1
    assert (
        next(item for item in access.accounts(owner) if item["id"] == reader.id)[
            "revision"
        ]
        == 1
    )


def test_revoke_reopens_and_preserves_jobs(case: Case) -> None:
    state, owner, _reader, access = case
    job = state.enqueue(owner, {"market": "EQUITY"})
    token, _ = state.login(owner.username, "only-synthetic-owner-pass")
    access.change(owner, owner.id, expected_revision=0, action="REVOKE_SESSIONS")
    with pytest.raises(AccessError):
        state.session(token)
    reopened = module.UserAdministration(AppState(state.path))
    assert reopened.history(owner)[0]["revoked_sessions"] == 1
    assert state.job(owner, job.id) == job


@pytest.mark.parametrize(
    "action,kwargs",
    [
        ("INVALID", {}),
        ("ROLE", {"role": "root"}),
        ("ROLE", {"role": "reader", "password": "not-allowed-password"}),
        ("PASSWORD", {"password": "short"}),
        ("PASSWORD", {"password": "x" * 129}),
        ("REVOKE_SESSIONS", {"role": "reader"}),
    ],
)
def test_closed_changes_never_mutate(
    case: Case, action: str, kwargs: ChangeFields
) -> None:
    _, owner, reader, access = case
    with pytest.raises(AccessError):
        access.change(owner, reader.id, expected_revision=0, action=action, **kwargs)
    assert access.history(owner) == []


def test_reader_and_forged_username_cannot_inspect_audit(case: Case) -> None:
    _, owner, reader, access = case
    for actor in [
        reader,
        replace(owner, username="forged"),
        replace(reader, role="owner"),
    ]:
        with pytest.raises(AccessError):
            access.history(actor)


def test_account_pagination_has_no_duplicates_or_missing_rows(case: Case) -> None:
    _, owner, reader, access = case
    first = access.accounts(owner, limit=1)
    assert isinstance(first[0]["id"], int)
    second = access.accounts(owner, after=first[0]["id"], limit=1)
    assert isinstance(second[0]["id"], int)
    assert [first[0]["id"], second[0]["id"]] == [owner.id, reader.id]
    assert access.accounts(owner, after=second[0]["id"], limit=1) == []


@pytest.mark.parametrize(
    "values",
    [{"after": -1}, {"after": 2**64}, {"limit": 0}, {"limit": 101}, {"limit": True}],
)
def test_invalid_account_pages_fail_closed(case: Case, values: PageFields) -> None:
    _, owner, _, access = case
    with pytest.raises(AccessError, match="account page"):
        access.accounts(owner, **values)
