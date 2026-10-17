# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared helpers for running the real interface against a stand-in engine."""

from __future__ import annotations

import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib
from gui_fakes import FakeEngine, write_sample_library

from istinbat.core import Language, Settings
from istinbat.core.models import ModelNotFoundError
from istinbat.core.progress import Progress, ProgressKey
from istinbat.gui.application import Application
from istinbat.gui.dispatch import run_on_main_thread
from istinbat.services import AppServices, Worker
from istinbat.storage import ConversationStore


def pump(seconds: float = 0.3, until=None) -> bool:
    """Run the GLib main loop for up to ``seconds`` (or until ``until()`` is true)."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.iteration(False):
            pass
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until() if until is not None else True


def make_settings(workdir: Path) -> Settings:
    settings = Settings()
    settings.paths.books_dir = str(workdir / "books")
    settings.paths.manifest_file = str(workdir / "manifest.json")
    settings.paths.vector_db = str(workdir / "db")
    settings.paths.conversations_db = str(workdir / "conversations.db")
    settings.paths.models_dir = str(workdir / "models")
    settings.app.language = Language.EN
    write_sample_library(settings)
    return settings


def build_app(
    workdir: Path,
    *,
    load_delay: float = 0.0,
    answer_delay: float = 0.0,
    fail_load: bool = False,
    unique: bool = False,
    answer: str | None = None,
    blocked: bool = False,
    downloader=None,
) -> tuple[Application, AppServices, FakeEngine]:
    """Create the real application wired to a FakeEngine (or to a failing model load)."""
    settings = make_settings(workdir)
    engine = FakeEngine(
        settings, delay=answer_delay, blocked=blocked, **({} if answer is None else {"answer": answer}),
    )

    def factory(_settings, progress):
        if progress:
            progress(Progress(0.4, ProgressKey.LOAD_RERANKER))
        time.sleep(load_delay)
        if fail_load:
            raise ModelNotFoundError("Language model is not configured")
        return engine

    services = AppServices(
        settings,
        Worker(run_on_main_thread),
        settings_path=workdir / "settings.json",
        store=ConversationStore(settings.paths.conversations_db),
        engine_factory=factory,
        downloader=downloader,
    )
    flags = Gio.ApplicationFlags.DEFAULT_FLAGS if unique else Gio.ApplicationFlags.NON_UNIQUE
    return Application(services, flags), services, engine


def start(app: Application, services: AppServices, size: tuple[int, int] = (1000, 640)):
    """Register and activate the app, then wait until loading has finished (successfully or not)."""
    app.register(None)
    app.activate()
    window = app.get_active_window()
    window.set_default_size(*size)
    pump(5, until=lambda: not services.loading and (services.engine or services.load_error))
    pump(0.2)
    return window
