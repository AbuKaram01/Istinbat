# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Serial background execution for blocking jobs.

Model inference blocks for seconds to minutes, so it must never run on the
interface thread. Every job runs on one dedicated thread, one at a time: the
engine is not thread-safe, and serializing guarantees that a search can never
overlap with an indexing run.

Results are handed back through a ``dispatch`` function supplied by the
interface (``GLib.idle_add`` in the GTK app), so callbacks always run on the
interface thread and may touch widgets directly.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Dispatch = Callable[[Callable[[], None]], None]


class Task:
    """Handle to a submitted job; cancellation is cooperative."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        """Poll this from inside the job; it is also what the engine's ``cancel`` expects."""
        return self._cancelled.is_set()


@dataclass
class _Job:
    run: Callable[[Task], Any]
    task: Task
    on_done: Callable[[Any], None] | None
    on_error: Callable[[Exception], None] | None
    on_skipped: Callable[[], None] | None


class Worker:
    def __init__(self, dispatch: Dispatch) -> None:
        self._dispatch = dispatch
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._pending = 0
        self._idle = threading.Condition()
        self._thread = threading.Thread(target=self._serve, name="istinbat-worker", daemon=True)
        self._thread.start()

    @property
    def is_busy(self) -> bool:
        """True while a job is running or queued."""
        with self._idle:
            return self._pending > 0

    def submit(
        self,
        run: Callable[[Task], Any],
        *,
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_skipped: Callable[[], None] | None = None,
    ) -> Task:
        """Queue ``run`` and return its task.

        ``on_done`` receives the job's return value, ``on_error`` the exception it
        raised, and ``on_skipped`` is called instead if the task was cancelled
        before it started. All callbacks run on the interface thread.
        """
        task = Task()
        with self._idle:
            self._pending += 1
        self._jobs.put(_Job(run, task, on_done, on_error, on_skipped))
        return task

    def post(self, callback: Callable[..., None], *args: Any) -> None:
        """Run ``callback(*args)`` on the interface thread; for updates sent from inside a job."""
        self._dispatch(lambda: callback(*args))

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until every submitted job has finished. Returns False on timeout."""
        with self._idle:
            return self._idle.wait_for(lambda: self._pending == 0, timeout)

    def shutdown(self, timeout: float | None = 5.0) -> None:
        """Stop the worker thread once the queue has drained."""
        self._jobs.put(None)
        self._thread.join(timeout)

    def _serve(self) -> None:
        while (job := self._jobs.get()) is not None:
            try:
                self._execute(job)
            finally:
                with self._idle:
                    self._pending -= 1
                    self._idle.notify_all()

    def _execute(self, job: _Job) -> None:
        if job.task.is_cancelled():
            self._notify(job.on_skipped)
            return
        try:
            result = job.run(job.task)
        except Exception as error:  # noqa: BLE001 - forwarded to the caller, never swallowed
            self._notify(job.on_error, error)
        else:
            self._notify(job.on_done, result)

    def _notify(self, callback: Callable[..., None] | None, *args: Any) -> None:
        if callback is not None:
            self._dispatch(lambda: callback(*args))
