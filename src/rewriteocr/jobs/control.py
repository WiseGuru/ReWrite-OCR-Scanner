"""Qt-free job control plane: pause, resume, cancel.

Pipelines call checkpoint() at safe points (between pages, between download
chunks). Pause blocks inside checkpoint; cancel raises JobCancelled, which
leaves everything already committed to the sidecar intact.
"""

from __future__ import annotations

import threading


class JobCancelled(Exception):
    pass


class JobControl:
    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._resume = threading.Event()
        self._resume.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._resume.set()  # wake a paused job so it can observe the cancel

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def checkpoint(self) -> None:
        """Block while paused; raise if cancelled."""
        if self._cancel.is_set():
            raise JobCancelled()
        while not self._resume.wait(timeout=0.2):
            if self._cancel.is_set():
                raise JobCancelled()
        if self._cancel.is_set():
            raise JobCancelled()
