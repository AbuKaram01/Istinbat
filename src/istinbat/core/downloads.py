# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Downloading the models of ``catalog`` from Hugging Face, with resume and cancellation.

Only the standard library is used. Each file is written to ``<name>.part`` and renamed
into place when complete, so a file that exists is a finished file, and an interrupted
download continues from where it stopped (HTTP ``Range``). Redirects, which Hugging Face
uses to hand large files to its CDN, are followed only when they stay on HTTPS.

The core never produces display text; failures are exceptions the interface describes.
"""

from __future__ import annotations

import http.client
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

from .. import __version__
from .catalog import ModelOption, RemoteFile
from .progress import CancelCheck

HUGGING_FACE = "https://huggingface.co"
_CHUNK_BYTES = 1024 * 1024
_SPACE_MARGIN_BYTES = 256 * 1024 * 1024
_TIMEOUT_SECONDS = 30.0
_MAX_BACKOFF_SECONDS = 30.0
_CONTENT_RANGE = re.compile(r"bytes\s+(?:\d+-\d+|\*)/(\d+)")
_RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}
_TRANSIENT_ERRORS = (urllib.error.URLError, ConnectionError, TimeoutError, http.client.HTTPException)


class DownloadError(Exception):
    """A download could not be completed."""


class DownloadCancelled(Exception):
    """The caller asked to stop. Partial files are kept so the download can resume."""


class NotEnoughSpaceError(DownloadError):
    def __init__(self, needed: int, available: int) -> None:
        super().__init__(f"{needed} bytes needed, {available} available")
        self.needed = needed
        self.available = available


@dataclass(frozen=True)
class DownloadProgress:
    done_bytes: int
    total_bytes: int      # An estimate until the real size of every file is known.
    file: str

    @property
    def fraction(self) -> float:
        return min(1.0, self.done_bytes / self.total_bytes) if self.total_bytes else 0.0


ProgressSink = Callable[[DownloadProgress], None]


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect that would leave HTTPS (the ``Range`` header survives a redirect)."""

    def __init__(self, allow_http: bool) -> None:
        self._allow_http = allow_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - stdlib signature
        scheme = urlparse(newurl).scheme
        if scheme != "https" and not self._allow_http:
            raise urllib.error.URLError(f"refusing a redirect to a {scheme or 'relative'} address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _total_from_headers(headers: http.client.HTTPMessage, offset: int, status: int) -> int | None:
    """The full size of the file, from ``Content-Range`` (206) or ``Content-Length`` (200)."""
    if status == http.client.PARTIAL_CONTENT:
        match = _CONTENT_RANGE.match(headers.get("Content-Range", ""))
        if match:
            return int(match.group(1))
        length = headers.get("Content-Length")
        return offset + int(length) if length and length.isdigit() else None
    length = headers.get("Content-Length")
    return int(length) if length and length.isdigit() else None


class _Download:
    """The state of one ``download_option`` call."""

    def __init__(
        self,
        option: ModelOption,
        folder: Path,
        progress: ProgressSink | None,
        cancel: CancelCheck | None,
        base_url: str,
        retries: int,
        sleep: Callable[[float], None],
    ) -> None:
        self._option = option
        self._folder = folder
        self._progress = progress
        self._cancel = cancel
        self._base_url = base_url.rstrip("/")
        self._retries = retries
        self._sleep = sleep
        self._opener = urllib.request.build_opener(_HttpsOnlyRedirects(base_url.startswith("http://")))
        self._sizes: dict[str, int] = {}     # Real sizes of the files whose size is known.
        self._finished_bytes = 0             # Bytes in files that are already complete.

    # -- Driver -----------------------------------------------------------------------

    def run(self) -> Path:
        self._folder.mkdir(parents=True, exist_ok=True)
        self._ensure_space(self._remaining_estimate())
        for file in self._option.files:
            target = self._folder / file.path
            if target.is_file():
                self._finish_file(file, target.stat().st_size)
            else:
                self._download_file(file, target)
        return self._folder

    def _finish_file(self, file: RemoteFile, size: int) -> None:
        self._sizes[file.path] = size
        self._finished_bytes += size

    def _download_file(self, file: RemoteFile, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        url = self._url(file)
        failures = 0
        while True:
            self._check_cancelled()
            before = part.stat().st_size if part.exists() else 0
            try:
                size = self._attempt(file, url, part)
            except _Restart:
                continue
            except urllib.error.HTTPError as error:
                if error.code not in _RETRYABLE_HTTP_CODES:
                    raise DownloadError(f"{error.code} {error.reason}: {file.path}") from error
                failure: Exception = error
            except _TRANSIENT_ERRORS as error:
                failure = error
            else:
                os.replace(part, target)
                self._finish_file(file, size)
                return

            gained = (part.stat().st_size if part.exists() else 0) > before
            failures = 0 if gained else failures + 1       # A flaky link that keeps progressing is not a failure.
            if failures > self._retries:
                raise DownloadError(f"the connection failed: {failure}") from failure
            self._sleep(min(2.0 ** failures, _MAX_BACKOFF_SECONDS))

    def _attempt(self, file: RemoteFile, url: str, part: Path) -> int:
        """Fetch (the rest of) one file; returns its final size. Raises on any interruption."""
        offset = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": f"Istinbat/{__version__}"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            response = self._opener.open(urllib.request.Request(url, headers=headers), timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as error:
            if error.code == http.client.REQUESTED_RANGE_NOT_SATISFIABLE and offset:
                self._settle_unsatisfiable_range(error, offset, part)
                return offset
            raise

        with response:
            status = response.status
            total = _total_from_headers(response.headers, offset, status)
            resumed = status == http.client.PARTIAL_CONTENT and offset > 0
            if not resumed:
                offset = 0                       # The server sent everything; start the file over.
            if total is not None:
                self._sizes[file.path] = total
                self._ensure_space(total - offset)
            written = offset
            with open(part, "ab" if resumed else "wb") as handle:
                while chunk := response.read(_CHUNK_BYTES):
                    self._check_cancelled()
                    handle.write(chunk)
                    written += len(chunk)
                    self._report(file, written)
        if total is not None and written != total:
            raise ConnectionError(f"received {written} of {total} bytes")
        return written

    @staticmethod
    def _settle_unsatisfiable_range(error: urllib.error.HTTPError, offset: int, part: Path) -> None:
        """A 416 means the partial file is already as long as the file, or longer (stale)."""
        match = _CONTENT_RANGE.match(error.headers.get("Content-Range", "") if error.headers else "")
        if match and int(match.group(1)) == offset:
            return                               # Already complete; only the rename was missing.
        part.unlink(missing_ok=True)
        raise _Restart

    # -- Helpers ----------------------------------------------------------------------

    def _url(self, file: RemoteFile) -> str:
        return f"{self._base_url}/{self._option.repo}/resolve/{self._option.revision}/{quote(file.path)}"

    def _check_cancelled(self) -> None:
        if self._cancel is not None and self._cancel():
            raise DownloadCancelled

    def _estimate_total(self) -> int:
        return sum(self._sizes.get(f.path, f.approx_bytes) for f in self._option.files)

    def _remaining_estimate(self) -> int:
        remaining = 0
        for file in self._option.files:
            target = self._folder / file.path
            if target.is_file():
                continue
            part = target.with_name(target.name + ".part")
            remaining += max(file.approx_bytes - (part.stat().st_size if part.exists() else 0), 0)
        return remaining

    def _report(self, file: RemoteFile, written: int) -> None:
        if self._progress is not None:
            done = self._finished_bytes + written
            self._progress(DownloadProgress(done, max(self._estimate_total(), done), file.path))

    def _ensure_space(self, needed: int) -> None:
        available = shutil.disk_usage(self._folder).free
        if needed + _SPACE_MARGIN_BYTES > available:
            raise NotEnoughSpaceError(needed, available)


class _Restart(Exception):
    """Internal: the partial file was discarded; fetch the file again from the start."""


def download_option(
    option: ModelOption,
    models_dir: str | Path,
    *,
    progress: ProgressSink | None = None,
    cancel: CancelCheck | None = None,
    base_url: str = HUGGING_FACE,
    retries: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Download every file of ``option`` into ``<models_dir>/<option.directory>``.

    Returns the path the settings should point to (``option.local_path``). Files that are
    already complete are skipped, partial files are resumed, and short connection drops
    are retried with a growing delay.

    Raises:
        DownloadCancelled: ``cancel()`` returned True. Partial files stay for the next attempt.
        NotEnoughSpaceError: the disk cannot hold the remaining download.
        DownloadError: the server refused, or the connection kept failing.
    """
    _Download(option, Path(models_dir) / option.directory, progress, cancel, base_url, retries, sleep).run()
    return option.local_path(models_dir)
