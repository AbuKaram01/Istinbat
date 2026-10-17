# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import threading
import time
from pathlib import Path

import pytest

from istinbat.core.catalog import EMBEDDER, LLMS, RERANKER
from istinbat.core.downloads import DownloadCancelled, DownloadProgress
from istinbat.core.settings import Settings, load_settings
from istinbat.services import AppServices, DownloadBusyError, DownloadEventKind, DownloadManager, Worker

LLM = LLMS[0]


class Harness:
    """Runs the manager with a fake downloader; callbacks queue up and run when ``flush`` is called."""

    def __init__(self, downloader, installed=None):
        self.settings = Settings()
        self.settings.paths.models_dir = "/models"
        self.queue = []
        self.events = []
        self.installed = installed if installed is not None else []
        self.manager = DownloadManager(
            self.settings, self.queue.append,
            on_installed=lambda option, path: self.installed.append((option.key, path)),
            downloader=downloader,
        )
        self.manager.subscribe(self.events.append)

    def finish(self):
        self.manager.join(5)
        self.flush()

    def flush(self):
        while self.queue:
            self.queue.pop(0)()

    def kinds(self):
        return [event.kind for event in self.events]


def instant(option, models_dir, *, progress, cancel):
    progress(DownloadProgress(5, 10, "a"))
    progress(DownloadProgress(10, 10, "a"))
    return Path(models_dir) / option.directory


def test_a_download_runs_in_the_configured_folder_and_installs_the_result_before_finishing():
    seen = {}

    def downloader(option, models_dir, *, progress, cancel):
        seen.update(option=option, models_dir=models_dir)
        return Path(models_dir) / "result"

    harness = Harness(downloader)
    harness.manager.start(EMBEDDER)
    assert harness.manager.active and harness.kinds() == [DownloadEventKind.STARTED]
    harness.finish()

    assert seen == {"option": EMBEDDER, "models_dir": "/models"}
    assert harness.installed == [("embedder", Path("/models/result"))]
    assert harness.kinds()[-1] is DownloadEventKind.FINISHED and not harness.manager.active
    assert harness.manager.current is None and harness.manager.progress is None


def test_progress_is_forwarded_and_the_last_update_is_never_dropped():
    harness = Harness(instant)
    harness.manager.start(RERANKER)
    harness.finish()

    progress = [e.progress for e in harness.events if e.kind is DownloadEventKind.PROGRESS]
    assert progress and progress[-1].done_bytes == 10


def test_progress_is_throttled_so_the_interface_is_not_flooded():
    def chatty(option, models_dir, *, progress, cancel):
        for done in range(1, 5001):
            progress(DownloadProgress(done, 10_000, "a"))
        return Path(models_dir)

    harness = Harness(chatty)
    harness.manager.start(EMBEDDER)
    harness.finish()
    assert len([e for e in harness.events if e.kind is DownloadEventKind.PROGRESS]) < 200


def test_only_one_download_runs_at_a_time():
    release = threading.Event()

    def slow(option, models_dir, *, progress, cancel):
        release.wait(5)
        return Path(models_dir)

    harness = Harness(slow)
    harness.manager.start(EMBEDDER)
    with pytest.raises(DownloadBusyError):
        harness.manager.start(RERANKER)
    release.set()
    harness.finish()
    harness.manager.start(RERANKER)                       # Free again once the first has finished.
    harness.finish()


def test_cancelling_reaches_the_downloader_and_installs_nothing():
    def waits_for_cancel(option, models_dir, *, progress, cancel):
        while not cancel():
            time.sleep(0.005)
        raise DownloadCancelled

    harness = Harness(waits_for_cancel)
    harness.manager.start(LLM)
    harness.manager.cancel()
    harness.finish()

    assert harness.kinds()[-1] is DownloadEventKind.CANCELLED and harness.installed == []
    assert not harness.manager.active


def test_a_failure_is_reported_with_its_error_and_the_manager_is_free_again():
    def broken(option, models_dir, *, progress, cancel):
        raise OSError("disk exploded")

    harness = Harness(broken)
    harness.manager.start(LLM)
    harness.finish()

    failed = harness.events[-1]
    assert failed.kind is DownloadEventKind.FAILED and "disk exploded" in str(failed.error)
    assert harness.installed == [] and not harness.manager.active


def test_a_listener_that_unsubscribes_hears_nothing_more():
    harness = Harness(instant)
    harness.manager.unsubscribe(harness.events.append)
    harness.manager.start(EMBEDDER)
    harness.finish()
    assert harness.events == []


def test_a_restarted_download_forgets_the_previous_progress():
    harness = Harness(instant)
    harness.manager.start(EMBEDDER)
    harness.finish()
    harness.manager.start(EMBEDDER)
    assert harness.manager.progress is None
    harness.finish()


# -- through AppServices ------------------------------------------------------------------------

@pytest.fixture
def services(tmp_path):
    settings = Settings()
    settings.paths.models_dir = str(tmp_path / "models")
    settings.paths.conversations_db = str(tmp_path / "c.db")
    queue = []
    worker = Worker(queue.append)
    created = AppServices(
        settings, worker, settings_path=tmp_path / "settings.json",
        downloader=lambda option, models_dir, *, progress, cancel: option.local_path(models_dir),
    )
    created.pending = queue
    yield created
    worker.shutdown(1)


def test_a_finished_download_becomes_the_selected_model_and_is_saved(services, tmp_path):
    services.downloads.start(LLMS[4])                      # E4B Q6_K_XL
    services.downloads.join(5)
    while services.pending:
        services.pending.pop(0)()

    expected = str(tmp_path / "models" / "gemma-4-E4B-it" / "gemma-4-E4B-it-UD-Q6_K_XL.gguf")
    assert services.settings.paths.llm_model == expected
    assert load_settings(tmp_path / "settings.json").paths.llm_model == expected


@pytest.mark.parametrize("option, attribute", [
    (EMBEDDER, "embedder_model"), (RERANKER, "reranker_model"), (LLMS[1], "llm_model"),
])
def test_use_model_sets_the_field_for_its_kind_only(services, option, attribute):
    services.use_model(option)
    paths = services.settings.paths
    changed = {name for name in ("embedder_model", "reranker_model", "llm_model") if getattr(paths, name)}
    assert changed == {attribute}
    assert getattr(paths, attribute) == str(option.local_path(paths.models_dir))
