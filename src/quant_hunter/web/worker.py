"""Single native worker with bounded stop and retained operational failure state."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread


class Worker:
    def __init__(self, process: Callable[[], bool]) -> None:
        self.process = process
        self.halt = Event()
        self.thread = Thread(target=self._run, name="qh-local-worker", daemon=False)
        self.failed = False

    @property
    def alive(self) -> bool:
        return self.thread.is_alive() and not self.failed

    def _run(self) -> None:
        while not self.halt.is_set():
            try:
                worked = self.process()
            except Exception:
                # Preserve queue state; do not spin or log arbitrary secret-bearing errors.
                self.failed = True
                return
            if not worked:
                self.halt.wait(0.25)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.halt.set()
        # Keep the process lease until all writes stop. Forceful process termination
        # is recovered as an interrupted attempt on next startup.
        self.thread.join()
