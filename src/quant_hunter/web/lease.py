"""OS-released process lease; crashes cannot leave a stale exclusive file claim."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import BinaryIO


class RuntimeLease:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "worker.lock"
        self.file: BinaryIO | None = None

    def acquire(self) -> None:
        if self.file is not None:
            raise RuntimeError("Runtime lease is already held")
        handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError(
                "Another process owns this runtime; do not run two workers"
            ) from exc
        self.file = handle

    def release(self) -> None:
        if self.file is not None:
            self.file.close()
            self.file = None
