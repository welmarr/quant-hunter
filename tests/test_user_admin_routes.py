"""Actual ASGI closed-input and owner/session boundary checks for production routes."""

import hmac
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from quant_hunter.web.state import AccessError, AppState, Session


def test_closed_owner_api_with_actual_sqlite_and_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_hunter.web import user_admin as service
    from quant_hunter.web import user_admin_routes as routes

    state = AppState(tmp_path / "application.sqlite3")
    owner = state.create_user(
        "owner", "synthetic-owner-password", "owner", bootstrap=True
    )
    reader = state.create_user(
        "reader", "synthetic-reader-password", "reader", bootstrap=False
    )
    owner_token, owner_session = state.login(owner.username, "synthetic-owner-password")
    reader_token, _reader_session = state.login(
        reader.username, "synthetic-reader-password"
    )
    app = FastAPI()

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        try:
            session = state.session(request.cookies.get("qh_session", ""))
        except AccessError:
            raise HTTPException(401, "Sign in") from None
        if owner and session.user.role != "owner":
            raise HTTPException(403, "Owner required")
        if mutation and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), session.csrf
        ):
            raise HTTPException(403, "CSRF required")
        return session

    routes.install_user_administration_routes(
        app, authenticated, service.UserAdministration(state)
    )
    with TestClient(app) as client:
        assert client.get("/api/administration/users").status_code == 401
        client.cookies.set("qh_session", reader_token)
        assert client.get("/api/administration/history").status_code == 403
        client.cookies.set("qh_session", owner_token)
        assert client.get("/api/administration/users").status_code == 200
        path = f"/api/administration/users/{reader.id}/change"
        body = {"action": "ROLE", "role": "researcher", "expected_revision": 0}
        assert client.post(path, json=body).status_code == 403
        client.headers["x-csrf-token"] = owner_session.csrf
        assert client.post(path, json=body).status_code == 200
        assert client.post(path, json=body).status_code == 409
        bad = client.post(
            path,
            json={"action": "PASSWORD", "password": "private", "expected_revision": 1},
        )
        assert bad.status_code == 400 and "private" not in bad.text
        assert (
            client.post(
                path,
                content='{"action":"ROLE","action":"PASSWORD"}',
                headers={"Content-Type": "application/json"},
            ).status_code
            == 400
        )
        assert client.post(path, content="x" * 4097).status_code == 413
        assert client.get("/api/administration/history").json()[0]["action"] == "ROLE"
        client.cookies.set("qh_session", reader_token)
        assert client.get("/api/administration/users").status_code == 401
