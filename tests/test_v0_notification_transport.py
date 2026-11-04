"""Fake-socket and real disposable offline-process Telegram boundary checks."""

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

from quant_hunter.notifications import telegram
from quant_hunter.notifications.types import (
    Notification,
    NotificationError,
    SendAuthorization,
    TelegramConfig,
    TelegramPolicy,
    VaultReference,
    digest,
    message_payload,
)

TOKEN = "123456789:" + "SyntheticTransportOnly12345"


def request() -> telegram.WireRequest:
    now = datetime.now(UTC)
    item = Notification(
        "N-1",
        "D-1",
        "TEST",
        "INFO",
        "SYNTHETIC",
        "Offline test",
        "No real external message.",
        now,
        now + timedelta(hours=1),
    )
    target = TelegramConfig(
        "OWNER", 1, VaultReference("TELEGRAM", "owner", "configuration"), "-12345", True
    )
    auth = SendAuthorization(
        "A-1",
        "OWNER",
        digest(item.payload),
        digest(target.payload),
        digest(message_payload(target, item)),
        "EXPLICIT_TEST",
        now,
        now + timedelta(seconds=30),
    )
    return telegram.WireRequest(
        TOKEN, target, item, auth, TelegramPolicy.REVIEWED_V0_TOKEN_PATH
    )


class Socket:
    closed = False

    def close(self) -> None:
        self.closed = True


class TLS:
    host = ""
    fail = False

    def wrap_socket(self, raw: Socket, *, server_hostname: str) -> Socket:
        self.host = server_hostname
        if self.fail:
            raise OSError(TOKEN)
        return raw


class Response:
    status = 200

    def __init__(self, item: telegram.WireRequest) -> None:
        self.headers: dict[str, str] = {}
        self.body = json.dumps(
            {
                "ok": True,
                "result": {
                    "message_id": 77,
                    "chat": {"id": int(item.config.chat_id)},
                    "text": item.event.telegram_text,
                },
            }
        ).encode()

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def read(self, count: int) -> bytes:
        return self.body[:count]


class HTTP:
    sock: Socket | None = None
    closed = False

    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, bytes | None, dict[str, str]]] = []

    def request(
        self, method: str, target: str, *, body: bytes | None, headers: dict[str, str]
    ) -> None:
        self.calls.append((method, target, body, headers))

    def getresponse(self) -> Response:
        return self.response

    def close(self) -> None:
        self.closed = True


def fake_wire(
    monkeypatch: pytest.MonkeyPatch, item: telegram.WireRequest
) -> tuple[Socket, TLS, HTTP, Response]:
    raw, tls, response = Socket(), TLS(), Response(item)
    connection = HTTP(response)
    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.socket.create_connection",
        lambda *a, **k: raw,
    )
    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.ssl.create_default_context", lambda: tls
    )
    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.http.client.HTTPSConnection",
        lambda *a, **k: connection,
    )
    return raw, tls, connection, response


def test_wire_is_fixed_host_post_with_only_reviewed_in_memory_path_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = request()
    _, tls, connection, _ = fake_wire(monkeypatch, item)
    assert telegram._wire(item).state == "SENT"
    assert tls.host == "api.telegram.org" and connection.closed
    assert len(connection.calls) == 1
    method, target, body, headers = connection.calls[0]
    assert method == "POST" and target == "/bot" + TOKEN + "/sendMessage"
    assert body == message_payload(item.config, item.event)
    assert TOKEN.encode() not in (body or b"") and TOKEN not in repr(headers)
    payload = json.loads(body or b"{}")
    assert "parse_mode" not in payload and "allow_paid_broadcast" not in payload


@pytest.mark.parametrize(
    "fault", ["encoding", "length", "malformed_length", "body", "redirect", "tls"]
)
def test_wire_faults_close_socket_and_do_not_follow_redirects(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    item = request()
    raw, tls, connection, response = fake_wire(monkeypatch, item)
    if fault == "encoding":
        response.headers["Content-Encoding"] = "gzip"
    elif fault == "length":
        response.headers["Content-Length"] = "65537"
    elif fault == "malformed_length":
        response.headers["Content-Length"] = "invalid"
    elif fault == "body":
        response.body = b"x" * 65537
    elif fault == "redirect":
        response.status = 302
        response.headers["Location"] = "http://127.0.0.1/private"
    else:
        tls.fail = True
    with pytest.raises((NotificationError, OSError)):
        telegram._wire(item)
    assert connection.closed and len(connection.calls) <= 1
    if fault == "tls":
        assert raw.closed


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "224.0.0.1", "192.0.2.1"],
)
def test_dns_refuses_nonpublic_addresses_before_credentials_leave_process(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", (address, 443))],
    )
    with pytest.raises(NotificationError, match="NONPUBLIC"):
        telegram._public_ip()


class PipeSink:
    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def send_bytes(self, value: bytes) -> None:
        self.frames.append(value)

    def close(self) -> None:
        return None


def test_child_never_serializes_secret_exception_or_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_: telegram.WireRequest) -> telegram.TelegramResult:
        raise RuntimeError("https://api.telegram.org/bot" + TOKEN + "/sendMessage")

    monkeypatch.setattr(telegram, "_wire", fail)
    monkeypatch.setattr(telegram, "_limits", lambda: None)
    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.logging.disable", lambda _: None
    )
    sink = PipeSink()
    telegram._child(request(), cast(Connection, sink))
    assert len(sink.frames) == 1 and TOKEN.encode() not in sink.frames[0]
    assert json.loads(sink.frames[0])["state"] == "UNKNOWN"


def _fixture_worker(item: telegram.WireRequest, send: Connection) -> None:
    send.send_bytes(
        b'{"state":"SENT","reason":"TELEGRAM_ACKNOWLEDGED","message_id":77}'
    )
    send.close()


def _hung_worker(item: telegram.WireRequest, send: Connection) -> None:
    time.sleep(15)


def _malformed_worker(item: telegram.WireRequest, send: Connection) -> None:
    send.send_bytes(b"malformed")
    send.close()


def _large_worker(item: telegram.WireRequest, send: Connection) -> None:
    send.send_bytes(b"x" * 16384)
    send.close()


@pytest.mark.parametrize("kind", ["positive", "timeout", "malformed", "large"])
def test_real_disposable_process_is_bounded_without_any_network(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    context = multiprocessing.get_context("spawn")
    worker = {
        "positive": _fixture_worker,
        "timeout": _hung_worker,
        "malformed": _malformed_worker,
        "large": _large_worker,
    }[kind]

    class FixtureContext:
        def Pipe(self, *, duplex: bool) -> tuple[Connection, Connection]:  # noqa: N802 - multiprocessing interface
            return cast(tuple[Connection, Connection], context.Pipe(duplex=duplex))

        def Process(  # noqa: N802 - multiprocessing interface
            self, *, target: object, args: tuple[object, ...], daemon: bool
        ) -> Any:
            return context.Process(target=worker, args=args, daemon=daemon)

    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.multiprocessing.get_context",
        lambda _: FixtureContext(),
    )
    if kind == "timeout":
        monkeypatch.setattr(telegram, "DEADLINE_SECONDS", 0.25)
    before = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    result = telegram.FixedTelegramHTTPS(network_enabled=True).send(request())
    assert result.state == ("SENT" if kind == "positive" else "UNKNOWN")
    assert time.monotonic() - started < 6
    assert {child.pid for child in multiprocessing.active_children()} == before


def _native_worker(item: telegram.WireRequest, send: Connection) -> None:
    try:
        telegram._limits()
        tls = ssl.create_default_context()
        incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        session = tls.wrap_bio(incoming, outgoing, server_hostname="api.telegram.org")
        try:
            session.do_handshake()
        except ssl.SSLWantReadError:
            assert outgoing.pending > 0
        assert tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED
        assert sys.modules["__main__"].__spec__.name == "quant_hunter.web.main"  # type: ignore[union-attr]
        assert "quant_hunter.web.api" not in sys.modules
        assert "quant_hunter.web.runtime" not in sys.modules
        limited = False
        try:
            bytearray(300 * 1024 * 1024)
        except MemoryError:
            limited = True
        if not limited:
            raise AssertionError("native allocation limit was not enforced")
        send.send_bytes(
            b'{"state":"SENT","reason":"NATIVE_TLS_MEMORY_LIMIT_PROOF","message_id":77}'
        )
    except BaseException:
        send.send_bytes(
            b'{"state":"UNKNOWN","reason":"NATIVE_PROOF_FAILED","message_id":null}'
        )
    finally:
        send.close()


@pytest.mark.skipif(sys.platform not in {"win32", "linux"}, reason="native profile")
def test_actual_production_main_spawn_native_limits_and_tls_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys.modules["__main__"],
        "__spec__",
        importlib.util.find_spec("quant_hunter.web.main"),
    )
    monkeypatch.setattr(telegram, "_child", _native_worker)
    before = {child.pid for child in multiprocessing.active_children()}
    result = telegram.FixedTelegramHTTPS(network_enabled=True).send(request())
    assert result.state == "SENT" and result.reason == "NATIVE_TLS_MEMORY_LIMIT_PROOF"
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_child_resource_failure_precedes_any_tls_or_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def unavailable() -> None:
        raise RuntimeError(TOKEN)

    def forbidden(_: telegram.WireRequest) -> telegram.TelegramResult:
        calls.append("unexpected")
        return telegram.TelegramResult("SENT", "WRONG", 1)

    monkeypatch.setattr(telegram, "_limits", unavailable)
    monkeypatch.setattr(telegram, "_wire", forbidden)
    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.logging.disable", lambda _: None
    )
    sink = PipeSink()
    telegram._child(request(), cast(Connection, sink))
    assert not calls and TOKEN.encode() not in sink.frames[0]
    assert json.loads(sink.frames[0])["state"] == "UNKNOWN"


@pytest.mark.parametrize(
    "fault",
    [
        "kill",
        "process_close",
        "reader_join",
        "reader_alive",
        "pipe_close",
        "first_join",
    ],
)
def test_unreaped_process_or_reader_cannot_skip_independent_pipe_cleanup(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    class StubPipe:
        closed = False

        def close(self) -> None:
            self.closed = True
            if fault == "pipe_close":
                raise OSError(TOKEN)

    receive, send = StubPipe(), StubPipe()
    cleanup: list[str] = []

    class StubProcess:
        pid = 12345

        def start(self) -> None:
            return None

        def join(self, timeout: float) -> None:
            cleanup.append("join")
            if fault == "first_join" and cleanup.count("join") == 1:
                raise OSError(TOKEN)

        def is_alive(self) -> bool:
            return fault == "kill" or (fault == "first_join" and "kill" not in cleanup)

        def kill(self) -> None:
            cleanup.append("kill")
            if fault == "kill":
                raise OSError(TOKEN)

        def close(self) -> None:
            if fault == "process_close":
                raise ValueError(TOKEN)

    class StubReader:
        ident = 1

        def __init__(
            self, *, target: object, args: tuple[Any, ...], daemon: bool
        ) -> None:
            self.output = args[1]

        def start(self) -> None:
            self.output.put(
                b'{"state":"SENT","reason":"TELEGRAM_ACKNOWLEDGED","message_id":77}'
            )

        def join(self, timeout: float) -> None:
            if fault == "reader_join":
                raise RuntimeError(TOKEN)

        def is_alive(self) -> bool:
            return fault == "reader_alive"

    class StubContext:
        def Pipe(self, *, duplex: bool) -> tuple[StubPipe, StubPipe]:  # noqa: N802 - multiprocessing interface
            return receive, send

        def Process(self, **kwargs: object) -> StubProcess:  # noqa: N802 - multiprocessing interface
            return StubProcess()

    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.multiprocessing.get_context",
        lambda _: StubContext(),
    )
    monkeypatch.setattr(
        "quant_hunter.notifications.telegram.threading.Thread", StubReader
    )
    result = telegram.FixedTelegramHTTPS(network_enabled=True).send(request())
    assert result.state == "UNKNOWN" and result.reason == "PROCESS_REAP_FAILED"
    assert receive.closed and send.closed
    assert TOKEN not in repr(result)
    if fault == "first_join":
        assert cleanup == ["join", "kill", "join"]
