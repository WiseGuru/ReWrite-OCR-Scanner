"""Qt job queue: one persistent worker thread, jobs run one at a time.

The UI layer never calls engines or the pipeline directly; everything goes
through here so pause, resume, cancel, and progress reporting are uniform.
"""

from __future__ import annotations

import logging
import traceback

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from rewriteocr.jobs.control import JobCancelled
from rewriteocr.jobs.definitions import Job

log = logging.getLogger("rewriteocr.jobs")


class JobRunner(QObject):
    """Lives on the worker thread. Executes one job per invocation."""

    job_started = Signal(object)
    job_progress = Signal(object, int, int, object)  # job, done, total, eta_s or None
    job_page_done = Signal(object, int)
    job_device_changed = Signal(object, str)
    job_message = Signal(object, str)
    job_finished = Signal(object, object)  # job, result
    job_failed = Signal(object, str)
    job_cancelled = Signal(object)

    @Slot(object)
    def run_job(self, job: Job) -> None:
        self.job_started.emit(job)
        try:
            result = job.run(_SignalReporter(self, job))
        except JobCancelled:
            log.info("Job cancelled: %s", job.description)
            self.job_cancelled.emit(job)
        except Exception as exc:
            log.exception("Job failed: %s", job.description)
            detail = f"{exc}\n\n{traceback.format_exc(limit=8)}"
            self.job_failed.emit(job, detail)
        else:
            self.job_finished.emit(job, result)


class _SignalReporter:
    """Adapts the pipeline's Reporter protocol onto runner signals. Emitted
    from the worker thread; queued connections deliver on the GUI thread."""

    def __init__(self, runner: JobRunner, job: Job) -> None:
        self._runner = runner
        self._job = job

    def progress(self, done: int, total: int, eta_s: float | None) -> None:
        self._runner.job_progress.emit(self._job, done, total, eta_s)

    def page_done(self, page_index: int) -> None:
        self._runner.job_page_done.emit(self._job, page_index)

    def device_changed(self, device: str) -> None:
        self._runner.job_device_changed.emit(self._job, device)

    def message(self, text: str) -> None:
        self._runner.job_message.emit(self._job, text)


class JobQueue(QObject):
    """GUI-thread facade: FIFO submission, one job active at a time."""

    _dispatch = Signal(object)

    job_started = Signal(object)
    job_progress = Signal(object, int, int, object)
    job_page_done = Signal(object, int)
    job_device_changed = Signal(object, str)
    job_message = Signal(object, str)
    job_finished = Signal(object, object)
    job_failed = Signal(object, str)
    job_cancelled = Signal(object)
    idle = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._thread.setObjectName("rewriteocr-jobs")
        self._runner = JobRunner()
        self._runner.moveToThread(self._thread)
        self._pending: list[Job] = []
        self._current: Job | None = None

        self._dispatch.connect(self._runner.run_job, Qt.QueuedConnection)
        self._runner.job_started.connect(self.job_started)
        self._runner.job_progress.connect(self.job_progress)
        self._runner.job_page_done.connect(self.job_page_done)
        self._runner.job_device_changed.connect(self.job_device_changed)
        self._runner.job_message.connect(self.job_message)
        self._runner.job_finished.connect(self._on_done_finished)
        self._runner.job_failed.connect(self._on_done_failed)
        self._runner.job_cancelled.connect(self._on_done_cancelled)
        self._thread.start()

    def shutdown(self) -> None:
        """Cancel everything and stop the worker thread."""
        self._pending.clear()
        if self._current is not None:
            self._current.control.cancel()
        self._thread.quit()
        self._thread.wait(10_000)

    @property
    def current(self) -> Job | None:
        return self._current

    @property
    def busy(self) -> bool:
        return self._current is not None

    def submit(self, job: Job) -> None:
        self._pending.append(job)
        self._maybe_dispatch()

    def pause_current(self) -> None:
        if self._current is not None:
            self._current.control.pause()

    def resume_current(self) -> None:
        if self._current is not None:
            self._current.control.resume()

    def cancel_current(self) -> None:
        if self._current is not None:
            self._current.control.cancel()

    def _maybe_dispatch(self) -> None:
        if self._current is None and self._pending:
            self._current = self._pending.pop(0)
            self._dispatch.emit(self._current)

    def _finish(self) -> None:
        self._current = None
        if self._pending:
            self._maybe_dispatch()
        else:
            self.idle.emit()

    @Slot(object, object)
    def _on_done_finished(self, job: Job, result: object) -> None:
        self.job_finished.emit(job, result)
        self._finish()

    @Slot(object, str)
    def _on_done_failed(self, job: Job, detail: str) -> None:
        self.job_failed.emit(job, detail)
        self._finish()

    @Slot(object)
    def _on_done_cancelled(self, job: Job) -> None:
        self.job_cancelled.emit(job)
        self._finish()
