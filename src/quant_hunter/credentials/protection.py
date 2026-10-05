"""DPAPI CurrentUser key wrapping and private-file policy; no ACL mutation."""

from __future__ import annotations

import ctypes
import os
import stat
import sys
from pathlib import Path

from quant_hunter.credentials.errors import VaultError


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _platform() -> str:
    return sys.platform


def windows_protect(data: bytes, *, decrypt: bool = False) -> bytes:
    """Use the current user, never LOCAL_MACHINE or interactive prompts."""
    if _platform() != "win32":
        raise VaultError("DPAPI_UNAVAILABLE")
    if not 1 <= len(data) <= 65_536:
        raise VaultError("KEY_BLOB_SIZE")
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise VaultError("DPAPI_UNAVAILABLE")
    crypt32 = loader("crypt32", use_last_error=True)
    kernel32 = loader("kernel32", use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_Blob),
    ]
    function.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data, len(data))
    incoming = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    try:
        if not function(
            ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(output)
        ):
            raise VaultError("DPAPI_FAILED")
        if not output.data or not 1 <= output.size <= 65_536:
            raise VaultError("DPAPI_INVALID_OUTPUT")
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(ctypes.addressof(buffer), 0, len(data))
        if output.data:
            if output.size <= 65_536:
                ctypes.memset(output.data, 0, output.size)
            kernel32.LocalFree(output.data)


def scheme() -> str:
    if _platform() == "win32":
        return "DPAPI_CURRENT_USER_V1"
    if _platform() == "linux":
        return "POSIX_PRIVATE_FILE_V1"
    raise VaultError("UNSUPPORTED_KEY_PROTECTION_PLATFORM")


def safe_path(path: Path) -> Path:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or str(path).startswith("\\\\")
        or path == Path(path.anchor)
    ):
        raise VaultError("INVALID_PRIVATE_PATH")
    for part in (*reversed(path.parents), path):
        if os.path.lexists(part):
            info = part.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise VaultError("PRIVATE_PATH_LINK_FORBIDDEN")
    return path


def permissions(path: Path, *, directory: bool) -> None:
    safe_path(path)
    info = path.lstat()
    if directory != stat.S_ISDIR(info.st_mode) or (
        not directory and not stat.S_ISREG(info.st_mode)
    ):
        raise VaultError("PRIVATE_PATH_TYPE")
    if not directory and info.st_nlink != 1:
        raise VaultError("PRIVATE_HARDLINK_FORBIDDEN")
    if _platform() == "linux":
        getuid = getattr(os, "getuid")  # noqa: B009 -- POSIX API absent from Windows stubs
        if info.st_uid != getuid() or stat.S_IMODE(info.st_mode) != (
            0o700 if directory else 0o600
        ):
            raise VaultError("PRIVATE_PERMISSIONS_REQUIRED")


def private_directory(path: Path) -> None:
    safe_path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    permissions(path, directory=True)


def publish_private(path: Path, data: bytes) -> None:
    """Exclusive creation leaves any interrupted object retained, never overwritten."""
    safe_path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        permissions(path, directory=False)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if _platform() == "linux":
        directory_flag = getattr(os, "O_DIRECTORY")  # noqa: B009 -- POSIX-only OS flag
        directory = os.open(path.parent, os.O_RDONLY | directory_flag)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def read_private(path: Path, maximum: int = 65_536) -> bytes:
    permissions(path, directory=False)
    with path.open("rb") as handle:
        content = handle.read(maximum + 1)
    if not content or len(content) > maximum:
        raise VaultError("PRIVATE_FILE_SIZE")
    return content
