"""Bounded text extraction in a disposable, resource-limited child process.

This is a resource boundary, not a host security sandbox or protection from a
compromised parser. No images, OCR, scripts, attachments or external commands run.
"""

from __future__ import annotations

import ctypes
import importlib
import io
import logging
import multiprocessing
import sys
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from .errors import PublicationError
from .validation import MAX_RAW, MAX_TEXT

MAX_DECODED = 8_000_000
MAX_PAGES = 200
MAX_SELECTED = 50
PROCESS_MEMORY = 256 * 1024 * 1024
DEADLINE = 10.0
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


def _limits() -> str:
    global _JOB
    if _platform() == "win32":
        loader = getattr(ctypes, "WinDLL")  # noqa: B009 -- absent from POSIX stubs
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
            raise PublicationError("PROCESS_LIMIT_UNAVAILABLE")
        if not api.AssignProcessToJobObject(handle, api.GetCurrentProcess()):
            api.CloseHandle(handle)
            raise PublicationError("PROCESS_LIMIT_UNAVAILABLE")
        # Kept open for the entire child's lifetime; the OS closes it on exit.
        _JOB = handle
        return "WINDOWS_JOB_MEMORY_CPU"
    if _platform() == "linux":
        resource = importlib.import_module("resource")
        resource.setrlimit(resource.RLIMIT_AS, (PROCESS_MEMORY, PROCESS_MEMORY))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return "LINUX_RLIMIT_AS_CPU"
    raise PublicationError("PROCESS_LIMIT_UNAVAILABLE")


def _pdf(raw: bytes, start: int, count: int) -> dict[str, Any]:
    from pypdf import PdfReader, apply_configuration
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        IndirectObject,
        StreamObject,
    )

    options: dict[str, Any] = {
        "maximum_declared_stream_length": MAX_RAW,
        "array_based_stream_maximum_output_length": MAX_DECODED,
        "zlib_maximum_output_length": MAX_DECODED,
        "zlib_maximum_recovery_input_length": MAX_RAW,
        "lzw_maximum_output_length": MAX_DECODED,
        "run_length_maximum_output_length": MAX_DECODED,
        "image_maximum_buffer_size": MAX_DECODED,
        "flate_maximum_columns": 20_000,
        "flate_maximum_row_length": MAX_DECODED,
        "page_tree_maximum_entries": 1000,
        "page_tree_maximum_depth": 30,
        "xform_maximum_invocations_per_extraction": 64,
        "jbig2dec_binary": None,
    }
    with apply_configuration(**options):
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise PublicationError("ENCRYPTED_PDF_REFUSED")
        total = len(reader.pages)
        if not 1 <= total <= MAX_PAGES or start >= total:
            raise PublicationError("PAGE_LIMIT")
        seen: set[tuple[int, int]] = set()
        nodes, decoded = 0, 0
        forbidden = {
            "/JavaScript",
            "/JS",
            "/AA",
            "/OpenAction",
            "/Launch",
            "/EmbeddedFiles",
            "/RichMedia",
            "/XFA",
        }

        def walk(value: Any, depth: int = 0) -> None:
            nonlocal nodes, decoded
            nodes += 1
            if depth > 40 or nodes > 20_000:
                raise PublicationError("PDF_GRAPH_LIMIT")
            if isinstance(value, IndirectObject):
                key = (value.idnum, value.generation)
                if key in seen:
                    return
                seen.add(key)
                walk(value.get_object(), depth + 1)
            elif isinstance(value, DictionaryObject):
                if forbidden.intersection(value):
                    raise PublicationError("ACTIVE_PDF_CONTENT_REFUSED")
                if (
                    isinstance(value, StreamObject)
                    and value.get("/Subtype") != "/Image"
                ):
                    filters = value.get("/Filter", [])
                    filters = filters if isinstance(filters, list) else [filters]
                    if any(
                        item
                        not in {
                            "/FlateDecode",
                            "/ASCIIHexDecode",
                            "/ASCII85Decode",
                            "/LZWDecode",
                            "/RunLengthDecode",
                        }
                        for item in filters
                    ):
                        raise PublicationError("PDF_FILTER_REFUSED")
                    remaining = MAX_DECODED - decoded
                    if remaining <= 0:
                        raise PublicationError("PDF_DECODED_LIMIT")
                    with apply_configuration(
                        zlib_maximum_output_length=remaining,
                        lzw_maximum_output_length=remaining,
                        run_length_maximum_output_length=remaining,
                        array_based_stream_maximum_output_length=remaining,
                    ):
                        decoded += len(value.get_data())
                    if decoded > MAX_DECODED:
                        raise PublicationError("PDF_DECODED_LIMIT")
                for child in value.values():
                    walk(child, depth + 1)
            elif isinstance(value, ArrayObject):
                for child in value:
                    walk(child, depth + 1)

        walk(reader.trailer)
        pages: list[dict[str, Any]] = []
        size = 0
        for index in range(start, min(total, start + count)):
            content = reader.pages[index].extract_text(extraction_mode="plain")
            size += len(content.encode("utf-8"))
            if size > MAX_TEXT:
                raise PublicationError("TEXT_LIMIT")
            pages.append({"page": index + 1, "text": content})
        nonempty = sum(bool(page["text"].strip()) for page in pages)
        access = (
            "UNAVAILABLE"
            if not nonempty
            else "COMPLETE"
            if start == 0 and len(pages) == total and nonempty == total
            else "PARTIAL"
        )
        return {
            "pages": pages,
            "total_pages": total,
            "access": access,
            "decoded_bytes": decoded,
            "extractor": "pypdf-6.19.0",
            "ocr": False,
        }


def _worker(connection: Connection, raw: bytes, start: int, count: int) -> None:
    logging.disable(logging.CRITICAL)
    sys.dont_write_bytecode = True
    try:
        boundary = _limits()
        result = _pdf(raw, start, count)
        result["resource_boundary"] = boundary
        connection.send({"ok": result})
    except PublicationError as error:
        connection.send({"error": error.code})
    except BaseException:
        # PDF exception messages may contain attacker-controlled document text.
        connection.send({"error": "PDF_EXTRACTION_FAILED"})
    finally:
        connection.close()


def _run(
    raw: bytes,
    start: int,
    count: int,
    *,
    deadline: float = DEADLINE,
    worker: Callable[..., None] = _worker,
) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    incoming, outgoing = context.Pipe(duplex=False)
    process = context.Process(
        target=worker, args=(outgoing, raw, start, count), daemon=True
    )
    try:
        process.start()
        outgoing.close()
        if not incoming.poll(deadline):
            raise PublicationError("EXTRACTION_TIMEOUT")
        try:
            message = incoming.recv()
        except EOFError:
            raise PublicationError("EXTRACTION_PROCESS_FAILED") from None
        if "error" in message:
            raise PublicationError(message["error"])
        return dict(message["ok"])
    finally:
        incoming.close()
        outgoing.close()
        if process.pid is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            if process.is_alive():
                raise PublicationError("EXTRACTION_REAP_FAILED")
            process.close()


def extract_pdf(
    raw: bytes, *, page_start: int = 0, page_count: int = MAX_SELECTED
) -> dict[str, Any]:
    if (
        not isinstance(raw, bytes)
        or not 0 < len(raw) <= MAX_RAW
        or not raw.startswith(b"%PDF-")
    ):
        raise PublicationError("INVALID_PDF_BYTES")
    if (
        type(page_start) is not int
        or not 0 <= page_start < MAX_PAGES
        or type(page_count) is not int
        or not 1 <= page_count <= MAX_SELECTED
    ):
        raise PublicationError("PAGE_LIMIT")
    return _run(raw, page_start, page_count)
