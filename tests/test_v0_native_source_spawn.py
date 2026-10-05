"""Production -m spawn initialization and real TLS trust loading, without network."""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import ssl
import sys
from multiprocessing.connection import Connection

import pytest

from quant_hunter.sources import process_http
from quant_hunter.sources.transport import Response


def _native_main_tls_worker(
    connection: Connection, _protocol: str, _payload: bytes
) -> None:
    """Fixed test entry: actual OS limits and certificate store, no DNS/socket."""
    sys.dont_write_bytecode = True
    try:
        process_http._limits()
        context = ssl.create_default_context()
        spec = sys.modules["__main__"].__spec__
        assert spec is not None
        proof = {
            "main_spec": spec.name,
            "api_loaded": "quant_hunter.web.api" in sys.modules,
            "runtime_loaded": "quant_hunter.web.runtime" in sys.modules,
            "verify_mode": int(context.verify_mode),
            "check_hostname": context.check_hostname,
            "memory_limit": process_http.PROCESS_MEMORY,
            "limits_established": True,
        }
        connection.send_bytes(
            process_http._frame(Response(200, json.dumps(proof).encode()))
        )
    except BaseException:
        connection.send_bytes(process_http._frame(error="NATIVE_TLS_FAILED"))
    finally:
        connection.close()


@pytest.mark.skipif(
    sys.platform not in {"win32", "linux"}, reason="native worker profile"
)
def test_production_main_spawn_leaves_capacity_for_actual_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exactly the preparation name produced by python -m quant_hunter.web.main.
    # The fresh child executes that real module as __mp_main__ before this target.
    monkeypatch.setattr(
        sys.modules["__main__"],
        "__spec__",
        importlib.util.find_spec("quant_hunter.web.main"),
    )
    monkeypatch.setattr(process_http, "_worker", _native_main_tls_worker)
    before = {p.pid for p in multiprocessing.active_children()}
    response = process_http.run("MACRO", b"{}")
    proof = json.loads(response.body)
    assert response.status == 200
    assert proof == {
        "main_spec": "quant_hunter.web.main",
        "api_loaded": False,
        "runtime_loaded": False,
        "verify_mode": int(ssl.CERT_REQUIRED),
        "check_hostname": True,
        "memory_limit": 256 * 1024 * 1024,
        "limits_established": True,
    }
    assert {p.pid for p in multiprocessing.active_children()} == before
