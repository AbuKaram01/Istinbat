# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The GTK application: lifecycle, actions, language switching and engine loading."""

from __future__ import annotations

import sys
from pathlib import Path

from .. import APP_ID, MIN_GTK, MIN_LIBADWAITA, __version__, winsupport

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, Gtk
except (ImportError, ValueError) as error:
    winsupport.report_missing_toolkit(error)
    raise
from ..core.progress import Progress
from ..core.settings import Language
from ..services import AppServices
from .dispatch import run_on_main_thread
from .window import MainWindow

_WEBSITE = "https://github.com/AbuKaram01/istinbat"
_PACKAGE_DIR = Path(__file__).resolve().parent


class Application(Adw.Application):
    def __init__(
        self,
        services: AppServices | None = None,
        flags: Gio.ApplicationFlags = Gio.ApplicationFlags.DEFAULT_FLAGS,
    ) -> None:
        super().__init__(application_id=APP_ID, flags=flags)
        self._services = services
        self._window: MainWindow | None = None
        for name, callback, shortcuts in (
            ("quit", lambda *_: self.quit(), ["<primary>q"]),
            ("about", self._on_about, []),
            ("preferences", self._on_preferences, ["<primary>comma"]),
            ("download-models", self._on_download_models, []),
            ("new-conversation", self._on_new_conversation, ["<primary>n"]),
            ("toggle-language", self._on_toggle_language, []),
            ("reload-engine", self._on_reload_engine, []),
        ):
            self._add_action(name, callback, shortcuts)

    @property
    def services(self) -> AppServices:
        assert self._services is not None, "services are created in do_startup"
        return self._services

    # -- Lifecycle ----------------------------------------------------------------

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        _require_toolkit_versions()
        if self._services is None:
            self._services = AppServices.create_default(run_on_main_thread)
        self._apply_direction()
        self._install_style()
        self.services.store.purge_older_than(self.services.settings.app.auto_delete_days)

    def do_activate(self) -> None:
        first_activation = self._window is None
        if first_activation:
            self._window = MainWindow(self, self.services)
        assert self._window is not None
        self._window.present()
        if first_activation and self.services.engine is None and not self.services.loading:
            self._start_engine_load()

    # -- Engine loading -----------------------------------------------------------

    def _start_engine_load(self) -> None:
        def on_progress(progress: Progress) -> None:
            if self._window is not None:
                self._window.on_load_progress(progress)

        def on_done() -> None:
            if self._window is not None:
                self._window.on_load_done()

        def on_error(error: Exception) -> None:
            if self._window is not None:
                self._window.on_load_error(error)

        self.services.load_engine(on_progress, on_done, on_error)

    def _on_reload_engine(self, *_args: object) -> None:
        if self.services.worker.is_busy or self._window is None:
            return
        self.services.unload_engine()
        self._window.show_loading()
        self._start_engine_load()

    # -- Language -----------------------------------------------------------------

    def _apply_direction(self) -> None:
        rtl = self.services.settings.app.language.is_rtl
        Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL if rtl else Gtk.TextDirection.LTR)

    def _on_toggle_language(self, *_args: object) -> None:
        window = self._window
        if window is None:
            return
        if self.services.worker.is_busy:
            window.show_toast(self.services.translate("language.busy"))
            return
        current = self.services.settings.app.language
        self.services.set_language(Language.AR if current is Language.EN else Language.EN)
        self._rebuild_window(window)

    def _rebuild_window(self, old: MainWindow) -> None:
        """Right-to-left layout only applies to new widgets, so a language change builds a new window."""
        conversation_id = old.current_conversation_id
        self._apply_direction()
        new = MainWindow(self, self.services)
        self._window = new
        new.present()
        new.open_conversation(conversation_id)
        old.destroy()

    # -- Actions ------------------------------------------------------------------

    def _add_action(self, name: str, callback, shortcuts: list[str]) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def _on_new_conversation(self, *_args: object) -> None:
        if self._window is not None and not self._window.is_busy and self.services.engine is not None:
            self._window.new_conversation()

    def _on_preferences(self, *_args: object) -> None:
        from .preferences import PreferencesDialog

        if self._window is not None:
            PreferencesDialog(self._window).present(self._window)

    def _on_download_models(self, *_args: object) -> None:
        from .preferences import PreferencesDialog

        if self._window is not None:
            dialog = PreferencesDialog(self._window)
            dialog.show_downloads()
            dialog.present(self._window)

    def _on_about(self, *_args: object) -> None:
        translate = self.services.translate
        about = Adw.AboutDialog(
            application_name="Istinbat",
            application_icon=APP_ID,
            version=__version__,
            developer_name="AbuKaram01",
            website=_WEBSITE,
            issue_url=f"{_WEBSITE}/issues",
            comments=translate("about.comments"),
            license_type=Gtk.License.AGPL_3_0,
        )
        about.present(self._window)

    # -- Resources ----------------------------------------------------------------

    def _install_style(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_path(str(_PACKAGE_DIR / "style.css"))
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # The icon is not installed system-wide when running from a source checkout, and Windows has no
        # system-wide icon folders at all: look next to the sources and in the environment's own share/icons.
        theme = Gtk.IconTheme.get_for_display(display)
        for icons in (_PACKAGE_DIR.parents[2] / "data" / "icons", Path(sys.prefix) / "share" / "icons"):
            if icons.is_dir():
                theme.add_search_path(str(icons))


def _require_toolkit_versions() -> None:
    """Fail early and clearly on a toolkit older than the interface was written for."""
    if (Adw.get_major_version(), Adw.get_minor_version()) < MIN_LIBADWAITA:
        raise SystemExit(f"Istinbat needs libadwaita {'.'.join(map(str, MIN_LIBADWAITA))} or newer.")
    if (Gtk.get_major_version(), Gtk.get_minor_version()) < MIN_GTK:
        raise SystemExit(f"Istinbat needs GTK {'.'.join(map(str, MIN_GTK))} or newer.")


def main() -> int:
    return Application().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
