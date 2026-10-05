"""Disposable fixed-protocol HTTPS workers with a parent-controlled total deadline.

This is a resource boundary, not a host security sandbox. Credentials exist only
in process memory and a local anonymous pipe, never files, logs or command lines.
"""

from __future__ import annotations

import base64
import ctypes
import importlib
import json
import logging
import multiprocessing
import re
import sys
import threading
import time
from multiprocessing.connection import Connection
from typing import Literal

from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, Response, SourceError

type ProtocolName = Literal["PUBLIC", "EQUITY", "MACRO", "PRIORITY"]
NETWORK_DEADLINE = 20.0
PROCESS_MEMORY = 256 * 1024 * 1024
MAX_REQUEST = 8192
MAX_FRAME = MAX_RESPONSE_BYTES + 1028
_JOB: object | None = None


class _Basic(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", ctypes.c_uint32),
        ("min_working", ctypes.c_size_t),
        ("max_working", ctypes.c_size_t),
        ("active_processes", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority", ctypes.c_uint32),
        ("scheduling", ctypes.c_uint32),
    ]


class _Extended(ctypes.Structure):
    _fields_ = [
        ("basic", _Basic),
        ("io", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


def _platform() -> str:
    return sys.platform


def _limits() -> None:
    """Fail closed if the disposable worker cannot establish native limits."""
    global _JOB
    if _platform() == "win32":
        loader = getattr(ctypes, "WinDLL")  # noqa: B009 - absent from POSIX stubs
        api = loader("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        api.CreateJobObjectW.restype = ctypes.c_void_p
        api.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        api.SetInformationJobObject.restype = ctypes.c_int
        api.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        api.AssignProcessToJobObject.restype = ctypes.c_int
        api.GetCurrentProcess.restype = ctypes.c_void_p
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = api.CreateJobObjectW(None, None)
        settings = _Extended()
        settings.basic.flags = 0x100 | 0x2000 | 0x8 | 0x2
        settings.basic.active_processes = 1
        settings.basic.process_time = 5 * 10_000_000
        settings.process_memory = PROCESS_MEMORY
        if not handle or not api.SetInformationJobObject(
            handle, 9, ctypes.byref(settings), ctypes.sizeof(settings)
        ):
            if handle:
                api.CloseHandle(handle)
            raise SourceError("PROCESS_LIMIT_UNAVAILABLE")
        if not api.AssignProcessToJobObject(handle, api.GetCurrentProcess()):
            api.CloseHandle(handle)
            raise SourceError("PROCESS_LIMIT_UNAVAILABLE")
        _JOB = handle  # OS closes this retained handle at child exit.
    elif _platform() == "linux":
        resource = importlib.import_module("resource")
        resource.setrlimit(resource.RLIMIT_AS, (PROCESS_MEMORY, PROCESS_MEMORY))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    else:
        raise SourceError("PROCESS_LIMIT_UNAVAILABLE")


def _dispatch(protocol: ProtocolName, payload: bytes) -> Response:
    """Closed dispatcher; input cannot select an arbitrary function or URL policy."""
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_REQUEST:
        raise SourceError("HTTP_REQUEST_BOUND")
    values = json.loads(payload)
    if not isinstance(values, dict):
        raise SourceError("HTTP_REQUEST_SCHEMA")
    if protocol == "MACRO":
        from quant_hunter.sources.macro_transport import MacroHTTPS, MacroRequest

        if set(values) != {"host", "target", "bearer"}:
            raise SourceError("HTTP_REQUEST_SCHEMA")
        response = MacroHTTPS._send_once(MacroRequest(**values))
    elif protocol == "PRIORITY":
        from quant_hunter.sources.priority_common import PriorityKey
        from quant_hunter.sources.priority_transport import (
            PriorityHTTPS,
            PriorityRequest,
        )

        if set(values) != {"host", "target", "key"}:
            raise SourceError("HTTP_REQUEST_SCHEMA")
        response = PriorityHTTPS._send_once(
            PriorityRequest(
                values["host"], values["target"], PriorityKey(values["key"])
            )
        )
    elif protocol == "EQUITY":
        from quant_hunter.sources._equity_transport import EquityHTTPS, EquityRequest

        if set(values) != {"host", "target", "user_agent", "key_id", "secret_key"}:
            raise SourceError("HTTP_REQUEST_SCHEMA")
        response = EquityHTTPS._send_once(EquityRequest(**values))
    elif protocol == "PUBLIC":
        from quant_hunter.sources.transport import HTTPSPublicTransport, Request

        if set(values) != {"method", "host", "target", "body"}:
            raise SourceError("HTTP_REQUEST_SCHEMA")
        body = (
            base64.b64decode(values["body"], validate=True)
            if values["body"] is not None
            else None
        )
        public = HTTPSPublicTransport._send_once(
            Request(values["method"], values["host"], values["target"], body)
        )
        return public
    else:
        raise SourceError("HTTP_PROTOCOL_REFUSED")
    return Response(response.status, response.body, response.retry_after)


def _frame(response: Response | None = None, *, error: str | None = None) -> bytes:
    header: dict[str, str | int | None]
    if error is not None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", error) is None:
            error = "NETWORK_FAILURE"
        header, body = {"error": error}, b""
    else:
        if (
            response is None
            or type(response.status) is not int
            or not 100 <= response.status <= 599
        ):
            raise SourceError("HTTP_RESPONSE_SCHEMA")
        if (
            not isinstance(response.body, bytes)
            or len(response.body) > MAX_RESPONSE_BYTES
        ):
            raise SourceError("RESPONSE_TOO_LARGE")
        retry = response.retry_after
        if retry is not None and (
            not isinstance(retry, str)
            or len(retry) > 128
            or not retry.isascii()
            or any(ord(c) < 32 for c in retry)
        ):
            raise SourceError("HTTP_RESPONSE_SCHEMA")
        header, body = {"status": response.status, "retry_after": retry}, response.body
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return len(encoded).to_bytes(4, "big") + encoded + body


def _decode(frame: bytes) -> Response:
    if not 4 < len(frame) <= MAX_FRAME:
        raise SourceError("HTTP_RESPONSE_SCHEMA")
    size = int.from_bytes(frame[:4], "big")
    if not 0 < size <= 1024 or len(frame) < size + 4:
        raise SourceError("HTTP_RESPONSE_SCHEMA")
    try:
        metadata = json.loads(frame[4 : 4 + size])
    except ValueError, UnicodeError:
        raise SourceError("HTTP_RESPONSE_SCHEMA") from None
    body = frame[size + 4 :]
    if not isinstance(metadata, dict):
        raise SourceError("HTTP_RESPONSE_SCHEMA")
    if set(metadata) == {"error"} and not body:
        code = metadata["error"]
        if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
            raise SourceError(code)
        raise SourceError("HTTP_RESPONSE_SCHEMA")
    if set(metadata) != {"status", "retry_after"}:
        raise SourceError("HTTP_RESPONSE_SCHEMA")
    result = Response(metadata["status"], body, metadata["retry_after"])
    _frame(result)  # Re-establish typed bounds in the receiving process.
    return result


def _worker(connection: Connection, protocol: ProtocolName, payload: bytes) -> None:
    logging.disable(logging.CRITICAL)
    sys.dont_write_bytecode = True
    try:
        _limits()
        response = _dispatch(protocol, payload)
        connection.send_bytes(_frame(response))
    except SourceError as error:
        connection.send_bytes(_frame(error=error.code))
    except BaseException:
        connection.send_bytes(_frame(error="NETWORK_FAILURE"))
    finally:
        connection.close()


def run(protocol: ProtocolName, payload: bytes) -> Response:
    """Execute one fixed request; bound all network stages and IPC reception.

    No callback parameter exists. Tests may replace the internal worker with a
    known module-level fixture; user input cannot provide executable code.
    """
    if protocol not in {"PUBLIC", "EQUITY", "MACRO", "PRIORITY"}:
        raise SourceError("HTTP_PROTOCOL_REFUSED")
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_REQUEST:
        raise SourceError("HTTP_REQUEST_BOUND")
    started = time.monotonic()
    context = multiprocessing.get_context("spawn")
    incoming, outgoing = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker, args=(outgoing, protocol, payload), daemon=True
    )
    complete = threading.Event()
    received: list[bytes | None] = []

    def receive() -> None:
        try:
            received.append(incoming.recv_bytes(MAX_FRAME))
        except EOFError, OSError:
            received.append(None)
        finally:
            complete.set()

    reader: threading.Thread | None = None
    try:
        process.start()
        outgoing.close()
        reader = threading.Thread(
            target=receive, name="qh-source-response", daemon=True
        )
        reader.start()
        remaining = max(0, NETWORK_DEADLINE - (time.monotonic() - started))
        if not complete.wait(remaining):
            raise SourceError("HTTP_TOTAL_TIMEOUT")
        if not received or received[0] is None:
            raise SourceError("HTTP_PROCESS_FAILED")
        return _decode(received[0])
    except SourceError:
        raise
    except OSError, RuntimeError, ValueError:
        raise SourceError("HTTP_PROCESS_FAILED") from None
    finally:
        cleanup_failed = False
        try:
            outgoing.close()
            if process.pid is not None:
                process.join(timeout=0.2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
                if process.is_alive():
                    cleanup_failed = True
                else:
                    process.close()
        except OSError, RuntimeError, ValueError:
            cleanup_failed = True
        finally:
            # Native termination failure must not skip closing the response pipe.
            try:
                incoming.close()
            except OSError, RuntimeError, ValueError:
                cleanup_failed = True
            if reader is not None:
                try:
                    reader.join(timeout=2)
                    cleanup_failed = cleanup_failed or reader.is_alive()
                except OSError, RuntimeError, ValueError:
                    cleanup_failed = True
        if cleanup_failed:
            raise SourceError("HTTP_REAP_FAILED") from None
