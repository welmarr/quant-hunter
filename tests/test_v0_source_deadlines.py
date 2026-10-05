"""Real spawned source boundaries with synthetic wire stages; never network."""

from __future__ import annotations

import ctypes
import json
import multiprocessing
import os
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

import pytest

from quant_hunter.sources import process_http as process
from quant_hunter.sources._equity_transport import EquityHTTPS, EquityRequest
from quant_hunter.sources.macro_transport import MacroHTTPS, MacroRequest
from quant_hunter.sources.priority_common import PriorityKey
from quant_hunter.sources.priority_transport import PriorityHTTPS, PriorityRequest
from quant_hunter.sources.transport import (
    HTTPSPublicTransport,
    Request,
    Response,
    SourceError,
)

KEY = "synthetic" + "0" * 23


def _request(protocol: str) -> Response:
    if protocol == "MACRO":
        value = MacroHTTPS().send(
            MacroRequest(
                "api.stlouisfed.org",
                "/fred/v2/release/observations?release_id=10&format=json&limit=100",
                KEY,
            )
        )
    elif protocol == "PRIORITY":
        value = PriorityHTTPS().send(
            PriorityRequest(
                "api.tradingeconomics.com",
                "/calendar/country/united%20states/2024-01-02/2024-01-03?f=json",
                PriorityKey(KEY),
            )
        )
    elif protocol == "EQUITY":
        value = EquityHTTPS().send(
            EquityRequest(
                "data.alpaca.markets",
                "/v2/stocks/bars?symbols=AAPL&timeframe=1Day&start=2024-01-01T00%3A00%3A00Z&end=2024-01-03T00%3A00%3A00Z&limit=100&adjustment=raw&feed=iex&asof=-&currency=USD&sort=asc",
                "Synthetic Source Test",
                KEY,
                KEY,
            )
        )
    else:
        return HTTPSPublicTransport().send(
            Request(
                "POST",
                "api.bls.gov",
                "/publicAPI/v1/timeseries/data/",
                b'{"seriesid":["CUUR0000SA0"],"startyear":"2024","endyear":"2024"}',
            )
        )
    return Response(value.status, value.body, value.retry_after)


class _Response:
    status = 200

    def __init__(self) -> None:
        self.remaining = b"{}"

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return {"Content-Length": "2", "Content-Encoding": "identity"}.get(
            name, default
        )

    def read1(self, size: int) -> bytes:
        value, self.remaining = self.remaining[:size], self.remaining[size:]
        return value


def _stall() -> None:
    Path(os.environ["QH_SOURCE_STALL_MARKER"]).write_bytes(b"entered-synthetic-stage")
    time.sleep(30)


def _wire_worker(
    connection: Connection,
    protocol: process.ProtocolName,
    payload: bytes,
    *,
    stage: str | None = None,
) -> None:
    module = {
        "MACRO": "quant_hunter.sources.macro_transport",
        "PRIORITY": "quant_hunter.sources.priority_transport",
        "EQUITY": "quant_hunter.sources._equity_transport",
        "PUBLIC": "quant_hunter.sources.transport",
    }[protocol]
    socket = Mock()
    secure = Mock()
    context = Mock()
    context.wrap_socket.return_value = secure
    http = Mock()
    http.getresponse.return_value = _Response()
    if stage == "headers":
        http.getresponse.side_effect = _stall
    with (
        patch(
            module + ".public_address",
            side_effect=(lambda _host: _stall()) if stage == "dns" else None,
            return_value="8.8.8.8",
        ),
        patch(module + ".socket.create_connection", return_value=socket),
        patch(module + ".ssl.create_default_context", return_value=context),
        patch(module + ".http.client.HTTPSConnection", return_value=http),
    ):
        process._worker(connection, protocol, payload)


def _successful_worker(
    connection: Connection, protocol: process.ProtocolName, payload: bytes
) -> None:
    _wire_worker(connection, protocol, payload)


def _dns_worker(
    connection: Connection, protocol: process.ProtocolName, payload: bytes
) -> None:
    _wire_worker(connection, protocol, payload, stage="dns")


def _headers_worker(
    connection: Connection, protocol: process.ProtocolName, payload: bytes
) -> None:
    _wire_worker(connection, protocol, payload, stage="headers")


@pytest.mark.parametrize("protocol", ["MACRO", "PRIORITY", "EQUITY", "PUBLIC"])
def test_real_spawned_bounded_wire_success(
    protocol: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(process, "_worker", _successful_worker)
    # The fixture calls the original trusted worker after replacing wire stages.
    response = _request(protocol)
    assert response.status == 200 and response.body == b"{}"


@pytest.mark.parametrize("protocol", ["MACRO", "PRIORITY", "EQUITY", "PUBLIC"])
@pytest.mark.parametrize("stage", ["dns", "headers"])
def test_real_total_deadline_kills_and_reaps_stalled_source(
    protocol: str, stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "stage.bin"
    monkeypatch.setenv("QH_SOURCE_STALL_MARKER", str(marker))
    monkeypatch.setattr(process, "NETWORK_DEADLINE", 3)
    monkeypatch.setattr(
        process, "_worker", _dns_worker if stage == "dns" else _headers_worker
    )
    previous = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    with pytest.raises(SourceError, match="HTTP_TOTAL_TIMEOUT"):
        _request(protocol)
    assert marker.read_bytes() == b"entered-synthetic-stage"
    assert time.monotonic() - started < 8
    assert {p.pid for p in multiprocessing.active_children()} == previous


def test_ipc_uses_bounded_binary_frames_and_validates_schema() -> None:
    response = Response(429, b"synthetic", "60")
    assert process._decode(process._frame(response)) == response
    assert (
        process._decode(process._frame(Response(200, b"x" * 2_000_000))).body
        == b"x" * 2_000_000
    )
    for value in [
        b"",
        b"xxxx",
        b"\x00\x00\x00\x04null",
        b"x" * (process.MAX_FRAME + 1),
    ]:
        with pytest.raises(SourceError):
            process._decode(value)
    for response in [
        Response(True, b"x"),
        Response(600, b"x"),
        Response(200, b"x" * 2_000_001),
        Response(200, b"x", "secret\r\nheader"),
    ]:
        with pytest.raises(SourceError):
            process._frame(response)
    with pytest.raises(SourceError, match="NETWORK_FAILURE"):
        process._decode(process._frame(error="untrusted synthetic secret error"))
    with pytest.raises(SourceError, match="HTTP_REQUEST_BOUND"):
        process.run("MACRO", b"x" * (process.MAX_REQUEST + 1))


def test_worker_sanitizes_exceptions_and_requires_closed_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process, "_limits", lambda: None)
    monkeypatch.setattr("logging.disable", lambda _level: None)
    connection = Mock()
    process._worker(connection, "MACRO", b"not json: synthetic secret")
    with pytest.raises(SourceError, match="NETWORK_FAILURE"):
        process._decode(connection.send_bytes.call_args.args[0])
    payload = json.dumps(
        {"host": "localhost", "target": "/arbitrary", "bearer": KEY}
    ).encode()
    process._worker(connection, "MACRO", payload)
    assert KEY.encode() not in connection.send_bytes.call_args.args[0]
    with pytest.raises(SourceError, match="ENDPOINT_NOT_ALLOWED"):
        process._decode(connection.send_bytes.call_args.args[0])


@pytest.mark.parametrize("protocol", ["MACRO", "PRIORITY", "EQUITY", "PUBLIC"])
def test_closed_dispatch_reconstructs_only_approved_request_types(
    protocol: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = Response(200, b"synthetic success")
    primitive = {
        "MACRO": MacroHTTPS,
        "PRIORITY": PriorityHTTPS,
        "EQUITY": EquityHTTPS,
        "PUBLIC": HTTPSPublicTransport,
    }[protocol]
    invoked = Mock(return_value=response)
    monkeypatch.setattr(primitive, "_send_once", invoked)

    def intercept(name: process.ProtocolName, payload: bytes) -> Response:
        assert name == protocol and len(payload) <= process.MAX_REQUEST
        return process._dispatch(name, payload)

    monkeypatch.setattr(process, "run", intercept)
    assert _request(protocol) == response
    assert invoked.call_count == 1
    constructed = invoked.call_args.args[0]
    constructed.__post_init__()
    assert KEY not in repr(constructed)
    with pytest.raises(SourceError, match="HTTP_REQUEST_SCHEMA"):
        process._dispatch(
            cast(process.ProtocolName, protocol),
            b'{"callback":"arbitrary.untrusted.function"}',
        )


def test_native_limits_fail_closed_without_mutating_parent_os(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process, "_JOB", None)
    monkeypatch.setattr(process, "_platform", lambda: "win32")
    api = Mock()
    api.CreateJobObjectW.return_value = 19
    api.GetCurrentProcess.return_value = 31
    api.SetInformationJobObject.return_value = 1
    api.AssignProcessToJobObject.return_value = 1
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=api), raising=False)
    process._limits()
    settings = ctypes.cast(
        api.SetInformationJobObject.call_args.args[2], ctypes.POINTER(process._Extended)
    ).contents
    assert settings.process_memory == 256 * 1024**2
    assert settings.basic.process_time == 5 * 10_000_000
    assert settings.basic.active_processes == 1
    assert settings.basic.flags == 0x100 | 0x2000 | 0x8 | 0x2
    api.AssignProcessToJobObject.assert_called_once_with(19, 31)
    api.CloseHandle.assert_not_called()
    for fail_stage in ("create", "configure", "assign"):
        api.CreateJobObjectW.return_value = 0 if fail_stage == "create" else 19
        api.SetInformationJobObject.return_value = 0 if fail_stage == "configure" else 1
        api.AssignProcessToJobObject.return_value = 0 if fail_stage == "assign" else 1
        with pytest.raises(SourceError, match="PROCESS_LIMIT_UNAVAILABLE"):
            process._limits()
    assert api.CloseHandle.call_count == 2
    monkeypatch.setattr(process, "_platform", lambda: "linux")
    resource = Mock()
    monkeypatch.setattr("importlib.import_module", Mock(return_value=resource))
    process._limits()
    assert resource.setrlimit.call_args_list == [
        ((resource.RLIMIT_AS, (process.PROCESS_MEMORY, process.PROCESS_MEMORY)),),
        ((resource.RLIMIT_CPU, (5, 5)),),
        ((resource.RLIMIT_CORE, (0, 0)),),
    ]
    monkeypatch.setattr(process, "_platform", lambda: "unsupported")
    with pytest.raises(SourceError, match="PROCESS_LIMIT_UNAVAILABLE"):
        process._limits()


def test_malformed_frames_and_dispatch_inputs_fail_without_code_or_data_echo() -> None:
    def frame(payload: bytes) -> bytes:
        return len(payload).to_bytes(4, "big") + payload

    for payload in (
        b"{",
        b"[]",
        b'{"error":"synthetic secret"}',
        b'{"status":200}',
        b'{"status":true,"retry_after":null}',
    ):
        with pytest.raises(SourceError, match="HTTP_RESPONSE_SCHEMA"):
            process._decode(frame(payload))
    for payload in (b"", b"x" * (process.MAX_REQUEST + 1)):
        with pytest.raises(SourceError, match="HTTP_REQUEST_BOUND"):
            process._dispatch("MACRO", payload)
    with pytest.raises(SourceError, match="HTTP_REQUEST_SCHEMA"):
        process._dispatch("MACRO", b"[]")
    with pytest.raises(SourceError, match="HTTP_PROTOCOL_REFUSED"):
        process._dispatch(cast(process.ProtocolName, "ARBITRARY"), b"{}")
    with pytest.raises(SourceError, match="HTTP_PROTOCOL_REFUSED"):
        process.run(cast(process.ProtocolName, "ARBITRARY"), b"{}")


def _invalid_ipc_worker(
    connection: Connection, _protocol: process.ProtocolName, _payload: bytes
) -> None:
    connection.send_bytes(b"invalid bounded frame")
    connection.close()


def _eof_worker(
    connection: Connection, _protocol: process.ProtocolName, _payload: bytes
) -> None:
    connection.close()


@pytest.mark.parametrize(
    "worker,code",
    [
        (_invalid_ipc_worker, "HTTP_RESPONSE_SCHEMA"),
        (_eof_worker, "HTTP_PROCESS_FAILED"),
    ],
)
def test_real_spawn_invalid_or_missing_response_has_sanitized_error(
    worker: object, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = {p.pid for p in multiprocessing.active_children()}
    monkeypatch.setattr(process, "_worker", worker)
    with pytest.raises(SourceError, match=code):
        _request("MACRO")
    assert {p.pid for p in multiprocessing.active_children()} == previous


def test_worker_success_uses_binary_ipc_and_always_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process, "_limits", lambda: None)
    monkeypatch.setattr("logging.disable", lambda _level: None)
    monkeypatch.setattr(
        process, "_dispatch", lambda _protocol, _payload: Response(200, b"synthetic")
    )
    channel = Mock()
    process._worker(channel, "MACRO", b"{}")
    assert process._decode(channel.send_bytes.call_args.args[0]) == Response(
        200, b"synthetic"
    )
    channel.send.assert_not_called()
    channel.close.assert_called_once()


def test_startup_failure_is_sanitized_and_closes_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Mock()
    incoming, outgoing, child = Mock(), Mock(), Mock()
    child.pid = None
    child.start.side_effect = OSError("synthetic sensitive startup details")
    context.Pipe.return_value = (incoming, outgoing)
    context.Process.return_value = child
    monkeypatch.setattr("multiprocessing.get_context", lambda _name: context)
    with pytest.raises(SourceError, match=r"^HTTP_PROCESS_FAILED$"):
        _request("MACRO")
    incoming.close.assert_called_once()
    outgoing.close.assert_called_once()


@pytest.mark.parametrize("failure", ["join", "still_alive"])
def test_native_reap_failure_still_closes_response_pipe(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = Mock()
    incoming, outgoing, child = Mock(), Mock(), Mock()
    incoming.recv_bytes.return_value = process._frame(Response(200, b"synthetic"))
    child.pid = 42
    child.is_alive.return_value = True
    if failure == "join":
        child.join.side_effect = OSError("synthetic native error details")
    context.Pipe.return_value = (incoming, outgoing)
    context.Process.return_value = child
    monkeypatch.setattr("multiprocessing.get_context", lambda _name: context)
    with pytest.raises(SourceError, match=r"^HTTP_REAP_FAILED$"):
        _request("MACRO")
    incoming.close.assert_called_once()
    assert outgoing.close.call_count >= 1
    if failure == "still_alive":
        child.kill.assert_called_once()
