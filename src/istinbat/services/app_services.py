# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""State shared by the whole interface: settings, storage, translations, worker and engine."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..core.catalog import ModelOption
from ..core.engine import Engine
from ..core.progress import ProgressCallback
from ..core.settings import Language, Settings, load_settings, save_settings
from ..i18n import Translator
from ..storage import ConversationStore
from .downloads import Downloader, DownloadManager
from .worker import Dispatch, Task, Worker

EngineFactory = Callable[[Settings, ProgressCallback | None], Engine]


class AppServices:
    """Owns everything windows share, so a window can be rebuilt without losing state.

    The language switch rebuilds the window (right-to-left layout only applies to
    newly created widgets); the engine, storage and worker survive it.
    """

    def __init__(
        self,
        settings: Settings,
        worker: Worker,
        *,
        settings_path: str | Path | None = None,
        store: ConversationStore | None = None,
        engine_factory: EngineFactory = Engine.load,
        downloader: Downloader | None = None,
    ) -> None:
        self.settings = settings
        self.worker = worker
        self.store = store or ConversationStore(settings.paths.conversations_db)
        self.translate = Translator(settings.app.language)
        self.engine: Engine | None = None
        self.load_error: Exception | None = None
        self.loading = False
        self._settings_path = settings_path
        self._engine_factory = engine_factory
        extra = {} if downloader is None else {"downloader": downloader}
        self.downloads = DownloadManager(
            settings, lambda callback: worker.post(callback), on_installed=self._use_downloaded_model, **extra,
        )

    @classmethod
    def create_default(cls, dispatch: Dispatch) -> AppServices:
        """Build the services from the user's saved settings."""
        return cls(load_settings(), Worker(dispatch))

    # -- Settings ---------------------------------------------------------------

    def save_settings(self) -> None:
        save_settings(self.settings, self._settings_path)

    def _use_downloaded_model(self, option: ModelOption, path: Path) -> None:
        """Point the settings at a model the user has just downloaded."""
        self.use_model(option, path)

    def use_model(self, option: ModelOption, path: Path | None = None) -> None:
        """Select a downloaded model; it takes effect the next time the models are loaded."""
        chosen = path or option.local_path(self.settings.paths.models_dir)
        setattr(self.settings.paths, option.kind.settings_attribute, str(chosen))
        self.save_settings()

    def set_language(self, language: Language) -> None:
        self.settings.app.language = language
        self.translate.set_language(language)
        self.save_settings()

    # -- Engine -----------------------------------------------------------------

    def load_engine(
        self,
        on_progress: Callable[..., None] | None = None,
        on_done: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> Task:
        """Load the engine in the background; callbacks run on the interface thread."""
        self.engine, self.load_error, self.loading = None, None, True

        def job(_task: Task) -> Engine:
            report = (lambda progress: self.worker.post(on_progress, progress)) if on_progress else None
            return self._engine_factory(self.settings, report)

        def loaded(engine: Engine) -> None:
            self.engine, self.loading = engine, False
            if on_done:
                on_done()

        def failed(error: Exception) -> None:
            self.load_error, self.loading = error, False
            if on_error:
                on_error(error)

        return self.worker.submit(job, on_done=loaded, on_error=failed)

    def unload_engine(self) -> None:
        self.engine = None
