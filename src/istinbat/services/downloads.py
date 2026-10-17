# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Model downloads as a background service shared by every window.

One download runs at a time, on its own thread, so the user can keep asking questions
while a large model downloads. Listeners are called on the interface thread through
``dispatch`` and may touch widgets. The service outlives the Preferences dialog: closing
and reopening it shows the download that is still running.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path

from ..core.catalog import ModelOption
from ..core.downloads import DownloadCancelled, DownloadProgress, download_option
from ..core.settings import Settings
from .worker import Dispatch

Downloader = Callable[..., Path]
_PROGRESS_INTERVAL_SECONDS = 0.25


class DownloadBusyError(RuntimeError):
    """Another download is already running."""


class DownloadEventKind(str, Enum):
    STARTED = "started"
    PROGRESS = "progress"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class DownloadEvent:
    kind: DownloadEventKind
    option: ModelOption
    progress: DownloadProgress | None = None
    error: Exception | None = None


Listener = Callable[[DownloadEvent], None]


class DownloadManager:
    def __init__(
        self,
        settings: Settings,
        dispatch: Dispatch,
        *,
        on_installed: Callable[[ModelOption, Path], None] | None = None,
        downloader: Downloader = download_option,
    ) -> None:
        self._settings = settings
        self._dispatch = dispatch
        self._on_installed = on_installed
        self._downloader = downloader
        self._listeners: list[Listener] = []
        self._cancelled = threading.Event()
        self._thread: threading.Thread | None = None
        self.current: ModelOption | None = None
        self.progress: DownloadProgress | None = None

    @property
    def active(self) -> bool:
        return self.current is not None

    # -- Listening --------------------------------------------------------------------

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _emit(self, event: DownloadEvent) -> None:
        for listener in list(self._listeners):
            listener(event)

    # -- Control (call from the interface thread) --------------------------------------

    def start(self, option: ModelOption) -> None:
        """Begin downloading ``option`` into the configured models folder."""
        if self.current is not None:
            raise DownloadBusyError(self.current.key)
        self.current, self.progress = option, None
        self._cancelled.clear()
        models_dir = self._settings.paths.models_dir
        self._thread = threading.Thread(
            target=self._run, args=(option, models_dir), name="istinbat-download", daemon=True,
        )
        self._emit(DownloadEvent(DownloadEventKind.STARTED, option))
        self._thread.start()

    def cancel(self) -> None:
        """Stop the running download; what was downloaded so far is kept for resuming."""
        self._cancelled.set()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the download thread to end (used by tests and at shutdown)."""
        if self._thread is not None:
            self._thread.join(timeout)

    # -- Worker thread ----------------------------------------------------------------

    def _run(self, option: ModelOption, models_dir: str) -> None:
        last_report = 0.0

        def report(progress: DownloadProgress) -> None:
            nonlocal last_report
            now = time.monotonic()
            if now - last_report >= _PROGRESS_INTERVAL_SECONDS or progress.done_bytes >= progress.total_bytes:
                last_report = now
                self._dispatch(lambda: self._on_progress(option, progress))

        try:
            path = self._downloader(option, models_dir, progress=report, cancel=self._cancelled.is_set)
        except DownloadCancelled:
            self._dispatch(partial(self._finish, DownloadEvent(DownloadEventKind.CANCELLED, option)))
        except Exception as error:  # noqa: BLE001 - shown to the user, never swallowed
            self._dispatch(partial(self._finish, DownloadEvent(DownloadEventKind.FAILED, option, error=error)))
        else:
            self._dispatch(partial(self._complete, option, path))

    # -- Interface thread (through dispatch) ---------------------------------------------

    def _on_progress(self, option: ModelOption, progress: DownloadProgress) -> None:
        if self.current is option:
            self.progress = progress
            self._emit(DownloadEvent(DownloadEventKind.PROGRESS, option, progress))

    def _complete(self, option: ModelOption, path: Path) -> None:
        if self._on_installed is not None:
            self._on_installed(option, path)
        self._finish(DownloadEvent(DownloadEventKind.FINISHED, option))

    def _finish(self, event: DownloadEvent) -> None:
        self.current, self.progress = None, None
        self._emit(event)
