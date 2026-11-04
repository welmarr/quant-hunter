"""Offline HTTPS and real disposable-process resource contracts; no network calls."""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import ssl
import sys
import time
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection
from typing import Any, cast

import pytest

from quant_hunter.paper_brokers import transport
from quant_hunter.paper_brokers.common import (
    MAX_BODY,
    BrokerError,
    PaperCredentials,
    Request,
)

KEY = "SyntheticWireKey12345678"
SECRET = "SyntheticWireSecret12345678"  # noqa: S105 - deliberately fake


class Socket:
    closed = False

    def close(self) -> None:
        self.closed = True


class TLS:
    def __init__(self) -> None:
        self.host: str | None = None
        self.fail = False

    def wrap_socket(self, raw: Socket, *, server_hostname: str) -> Socket:
        self.host = server_hostname
        if self.fail:
            raise OSError(SECRET)
        return raw


class HTTPResponse:
    status = 200

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.body = b'{"fixture":true}'
        self.failure: Exception | None = None

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def read(self, count: int) -> bytes:
        if self.failure is not None:
            raise self.failure
        return self.body[:count]


class HTTPConnection:
    sock: Socket | None = None
    closed = False

    def __init__(self, response: HTTPResponse) -> None:
        self.response = response
        self.method = ""
        self.target = ""
        self.headers: dict[str, str] = {}
        self.body: bytes | None = None

    def request(
        self, method: str, target: str, *, body: bytes | None, headers: dict[str, str]
    ) -> None:
        self.method, self.target, self.body, self.headers = (
            method,
            target,
            body,
            headers,
        )

    def getresponse(self) -> HTTPResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def fake_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Socket, TLS, HTTPConnection, HTTPResponse]:
    raw, tls, reply = Socket(), TLS(), HTTPResponse()
    connection = HTTPConnection(reply)
    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.socket.create_connection",
        lambda *args, **kwargs: raw,
    )
    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.ssl.create_default_context", lambda: tls
    )
    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.http.client.HTTPSConnection",
        lambda *args, **kwargs: connection,
    )
    return raw, tls, connection, reply


def test_authorization_expiring_during_tls_sends_no_http_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from quant_hunter.paper_brokers.common import (
        BrokerConfig,
        OrderIntent,
        RiskAuthorization,
        action_bytes,
        digest,
    )

    _, tls, connection, _ = fake_wire(monkeypatch)
    now = datetime.now(UTC)
    config = BrokerConfig(
        "ALPACA",
        "OWNER",
        "11111111-1111-1111-1111-111111111111",
        PaperCredentials(KEY, SECRET),
    )
    order = OrderIntent("CLIENT-1", "TEST", Decimal(10), "BUY", "MARKET", "DAY")
    payload = action_bytes("SUBMIT", order, None)
    permit = RiskAuthorization(
        "AUTH-1",
        "OWNER",
        config.account_id,
        "ALPACA",
        "EXP-EXISTING",
        "STR-EXISTING",
        digest(payload),
        1,
        now,
        now + timedelta(seconds=10),
    )
    clock = [now]

    class Clock:
        @staticmethod
        def now(zone: object) -> datetime:
            return clock[0]

    wrap = tls.wrap_socket

    def delayed(raw: Socket, *, server_hostname: str) -> Socket:
        clock[0] = permit.expires_at + timedelta(seconds=1)
        return wrap(raw, server_hostname=server_hostname)

    monkeypatch.setattr(transport, "datetime", Clock)
    monkeypatch.setattr(tls, "wrap_socket", delayed)
    body = json.dumps(
        {
            "qty": "10",
            "time_in_force": "day",
            "client_order_id": "CLIENT-1",
            "symbol": "TEST",
            "side": "buy",
            "type": "market",
            "order_class": "simple",
            "extended_hours": False,
        }
    ).encode()
    with pytest.raises(BrokerError, match="EXPIRED"):
        transport._wire(
            Request(
                "ALPACA",
                "POST",
                "/v2/orders",
                config.credentials,
                body,
                permit,
                config,
                payload,
            )
        )
    assert connection.method == "" and connection.closed


@pytest.mark.parametrize("provider", ["ALPACA", "OANDA"])
def test_actual_wire_primitive_pins_public_ip_validates_tls_name_and_keeps_auth_in_headers(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, tls, connection, _ = fake_wire(monkeypatch)
    request = Request(
        provider,
        "GET",
        "/v2/account" if provider == "ALPACA" else "/v3/accounts",
        PaperCredentials(KEY, SECRET if provider == "ALPACA" else None),
    )
    result = transport._wire(request)
    assert result.status == 200 and tls.host == request.host and connection.closed
    assert connection.body is None and KEY not in connection.target
    if provider == "ALPACA":
        assert connection.headers["APCA-API-KEY-ID"] == KEY
        assert connection.headers["APCA-API-SECRET-KEY"] == SECRET
    else:
        assert connection.headers["Authorization"] == "Bearer " + KEY
        assert connection.headers["Accept-Datetime-Format"] == "RFC3339"


@pytest.mark.parametrize(
    "kind",
    [
        "compressed",
        "large-length",
        "bad-length",
        "large-body",
        "timeout",
        "socket",
        "tls",
    ],
)
def test_wire_resource_and_tls_failures_are_sanitized_and_closed(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, tls, connection, reply = fake_wire(monkeypatch)
    if kind == "compressed":
        reply.headers["Content-Encoding"] = "gzip"
    elif kind == "large-length":
        reply.headers["Content-Length"] = "2097153"
    elif kind == "bad-length":
        reply.headers["Content-Length"] = "invalid"
    elif kind == "large-body":
        reply.body = b"x" * 2097153
    elif kind == "timeout":
        reply.failure = TimeoutError(SECRET)
    elif kind == "socket":
        reply.failure = OSError(SECRET)
    else:
        tls.fail = True
    with pytest.raises(BrokerError) as failure:
        transport._wire(
            Request("ALPACA", "GET", "/v2/account", PaperCredentials(KEY, SECRET))
        )
    assert SECRET not in str(failure.value) and connection.closed
    if kind == "tls":
        assert raw.closed


def test_redirect_is_returned_without_following_any_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, connection, reply = fake_wire(monkeypatch)
    reply.status = 302
    reply.headers["Location"] = "http://127.0.0.1/private"
    result = transport._wire(
        Request("ALPACA", "GET", "/v2/account", PaperCredentials(KEY, SECRET))
    )
    assert result.status == 302 and connection.target == "/v2/account"


def _fixture_process(request: Request, connection: Connection) -> None:
    header = json.dumps({"status": 200, "retry_after": None}).encode()
    connection.send_bytes(
        len(header).to_bytes(4, "big") + header + b'{"offline_process_fixture":true}'
    )
    connection.close()


def _hanging_process(request: Request, connection: Connection) -> None:
    time.sleep(30)


class ProcessContext:
    def __init__(self, real: Any, *, hang: bool) -> None:
        self.real = real
        self.hang = hang
        self.process: Any = None

    def Pipe(self, *, duplex: bool) -> tuple[Connection, Connection]:  # noqa: N802 - mirrors multiprocessing interface
        return cast(tuple[Connection, Connection], self.real.Pipe(duplex=duplex))

    def Process(self, *, target: object, args: tuple[object, ...], daemon: bool) -> Any:  # noqa: N802 - mirrors multiprocessing interface
        self.process = self.real.Process(
            target=_hanging_process if self.hang else _fixture_process,
            args=args,
            daemon=daemon,
        )
        return self.process


def test_real_disposable_child_transfers_bounded_frame_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ProcessContext(multiprocessing.get_context("spawn"), hang=False)
    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.multiprocessing.get_context",
        lambda method: context,
    )
    result = transport.FixedPaperHTTPS(network_enabled=True).send(
        Request("ALPACA", "GET", "/v2/account", PaperCredentials(KEY, SECRET))
    )
    assert result.body == b'{"offline_process_fixture":true}'
    with pytest.raises(ValueError, match="closed"):
        context.process.is_alive()


def test_real_hanging_child_is_terminated_at_parent_deadline_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ProcessContext(multiprocessing.get_context("spawn"), hang=True)
    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.multiprocessing.get_context",
        lambda method: context,
    )
    monkeypatch.setattr(transport, "DEADLINE_SECONDS", 0.2)
    started = time.monotonic()
    with pytest.raises(BrokerError, match="TIMEOUT"):
        transport.FixedPaperHTTPS(network_enabled=True).send(
            Request("ALPACA", "GET", "/v2/account", PaperCredentials(KEY, SECRET))
        )
    assert time.monotonic() - started < 5
    with pytest.raises(ValueError, match="closed"):
        context.process.is_alive()


@pytest.mark.parametrize("kind", ["empty", "oversized", "invalid", "mixed", "failure"])
def test_dns_contract_is_bounded_and_checks_every_answer(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers: list[tuple[object, ...]] = [(2, 1, 6, "", ("8.8.8.8", 443))]
    if kind == "empty":
        answers = []
    elif kind == "oversized":
        answers *= 33
    elif kind == "invalid":
        answers = [(2, 1, 6, "", ("not-an-address", 443))]
    elif kind == "mixed":
        answers.append((2, 1, 6, "", ("127.0.0.1", 443)))

    def resolve(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        if kind == "failure":
            raise OSError(SECRET)
        return answers

    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.socket.getaddrinfo", resolve
    )
    with pytest.raises(BrokerError) as failure:
        transport.public_ip("paper-api.alpaca.markets")
    assert SECRET not in str(failure.value)


class SendPipe:
    frame = b""
    closed = False

    def send_bytes(self, frame: bytes) -> None:
        self.frame = frame

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("fail", [False, True])
def test_child_serializes_only_bounded_success_or_fixed_failure(
    monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    from quant_hunter.paper_brokers.common import Response

    def wire(request: Request) -> Response:
        if fail:
            raise RuntimeError(SECRET)
        return Response(200, b"{}")

    monkeypatch.setattr(transport, "_wire", wire)
    monkeypatch.setattr(transport, "_limits", lambda: None)
    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.logging.disable", lambda _: None
    )
    pipe = SendPipe()
    transport._child(
        Request("ALPACA", "GET", "/v2/account", PaperCredentials(KEY, SECRET)),
        cast(Connection, pipe),
    )
    assert pipe.closed and SECRET.encode() not in pipe.frame
    assert pipe.frame == b"FAIL" if fail else pipe.frame.endswith(b"{}")


def _native_worker(request: Request, send: Connection) -> None:
    try:
        transport._limits()
        tls = ssl.create_default_context()
        incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        session = tls.wrap_bio(incoming, outgoing, server_hostname=request.host)
        try:
            session.do_handshake()
        except ssl.SSLWantReadError:
            assert outgoing.pending > 0
        assert tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED
        assert sys.modules["__main__"].__spec__.name == "quant_hunter.web.main"  # type: ignore[union-attr]
        assert "quant_hunter.web.api" not in sys.modules
        limited = False
        try:
            bytearray(300 * 1024 * 1024)
        except MemoryError:
            limited = True
        if not limited:
            raise AssertionError("native allocation limit was not enforced")
        header = b'{"status":200,"retry_after":null}'
        send.send_bytes(
            len(header).to_bytes(4, "big") + header + b'{"native_limit_proof":true}'
        )
    except BaseException:
        send.send_bytes(b"FAIL")
    finally:
        send.close()


@pytest.mark.skipif(sys.platform not in {"win32", "linux"}, reason="native profile")
def test_production_main_spawn_native_limits_and_tls_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys.modules["__main__"],
        "__spec__",
        importlib.util.find_spec("quant_hunter.web.main"),
    )
    monkeypatch.setattr(transport, "_child", _native_worker)
    before = {child.pid for child in multiprocessing.active_children()}
    result = transport.FixedPaperHTTPS(network_enabled=True).send(
        Request("ALPACA", "GET", "/v2/account", PaperCredentials(KEY, SECRET))
    )
    assert result.body == b'{"native_limit_proof":true}'
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_unavailable_native_limit_precedes_all_wire_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def limits() -> None:
        raise RuntimeError(SECRET)

    def wire(_: Request) -> None:
        calls.append(True)

    monkeypatch.setattr(transport, "_limits", limits)
    monkeypatch.setattr(transport, "_wire", wire)
    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.logging.disable", lambda _: None
    )
    pipe = SendPipe()
    transport._child(
        Request("ALPACA", "GET", "/v2/account", PaperCredentials(KEY, SECRET)),
        cast(Connection, pipe),
    )
    assert pipe.closed and pipe.frame == b"FAIL" and not calls


def _oversized_worker(request: Request, send: Connection) -> None:
    send.send_bytes(b"x" * (MAX_BODY + 2048))
    send.close()


def test_oversized_native_frame_fails_and_reaps_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transport, "_child", _oversized_worker)
    before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(BrokerError, match="NETWORK_FAILURE"):
        transport.FixedPaperHTTPS(network_enabled=True).send(
            Request("ALPACA", "GET", "/v2/account", PaperCredentials(KEY, SECRET))
        )
    assert {child.pid for child in multiprocessing.active_children()} == before


@pytest.mark.parametrize(
    "fault",
    [
        "kill",
        "process_close",
        "reader_join",
        "reader_alive",
        "pipe_close",
        "start",
        "first_join",
    ],
)
def test_cleanup_faults_cannot_skip_independent_handles(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    class StubPipe:
        closed = False

        def close(self) -> None:
            self.closed = True
            if fault == "pipe_close":
                raise OSError(SECRET)

    receive, send = StubPipe(), StubPipe()
    cleanup: list[str] = []

    class StubProcess:
        pid = None if fault == "start" else 12345

        def start(self) -> None:
            if fault == "start":
                raise OSError(SECRET)

        def join(self, timeout: float) -> None:
            cleanup.append("join")
            if fault == "first_join" and cleanup.count("join") == 1:
                raise OSError(SECRET)

        def is_alive(self) -> bool:
            return fault == "kill" or (fault == "first_join" and "kill" not in cleanup)

        def kill(self) -> None:
            cleanup.append("kill")
            if fault == "kill":
                raise OSError(SECRET)

        def close(self) -> None:
            if fault == "process_close":
                raise ValueError(SECRET)

    class StubReader:
        ident = None if fault == "start" else 1

        def __init__(
            self, *, target: object, args: tuple[Any, ...], daemon: bool
        ) -> None:
            self.output = args[1]

        def start(self) -> None:
            header = b'{"status":200,"retry_after":null}'
            self.output.put(len(header).to_bytes(4, "big") + header + b"{}")

        def join(self, timeout: float) -> None:
            if fault == "reader_join":
                raise RuntimeError(SECRET)

        def is_alive(self) -> bool:
            return fault == "reader_alive"

    class StubContext:
        def Pipe(self, *, duplex: bool) -> tuple[StubPipe, StubPipe]:  # noqa: N802 -- multiprocessing API
            return receive, send

        def Process(self, **kwargs: object) -> StubProcess:  # noqa: N802 -- multiprocessing API
            return StubProcess()

    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.multiprocessing.get_context",
        lambda _: StubContext(),
    )
    monkeypatch.setattr(
        "quant_hunter.paper_brokers.transport.threading.Thread", StubReader
    )
    with pytest.raises(
        BrokerError,
        match="NETWORK_FAILURE" if fault == "start" else "PROCESS_REAP_FAILED",
    ) as error:
        transport.FixedPaperHTTPS(network_enabled=True).send(
            Request("ALPACA", "GET", "/v2/account", PaperCredentials(KEY, SECRET))
        )
    assert receive.closed and send.closed and SECRET not in str(error.value)
    if fault == "first_join":
        assert cleanup == ["join", "kill", "join"]
