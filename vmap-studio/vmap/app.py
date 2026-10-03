"""Desktop entry point: `vmap-studio`, `python -m vmap`, or `vmap open FILE`.

Set VMAP_DATA_DIR to keep settings, themes and logs in a custom (e.g. portable) folder.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QEvent, QStandardPaths, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from vmap import APP_NAME, __version__
from vmap.i18n import load_translations, tr

log = logging.getLogger("vmap")
ORG_NAME = "VMapStudio"
DATA_DIR_ENV = "VMAP_DATA_DIR"
_in_hook = False


class VMapApplication(QApplication):
    """Adds macOS Finder 'open file' support (QFileOpenEvent)."""
    file_open_requested = Signal(str)

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self._ready = False
        self._pending: list[str] = []

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            if path:
                if self._ready:
                    self.file_open_requested.emit(path)
                else:
                    self._pending.append(path)
            return True
        return super().event(event)

    def mark_ready(self) -> list[str]:
        self._ready = True
        pending, self._pending = self._pending, []
        return pending


def _data_dir() -> Optional[Path]:
    env = os.environ.get(DATA_DIR_ENV)
    if env:
        return Path(env).expanduser()
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(location) if location else None


def _setup_logging(data_dir: Optional[Path]) -> Optional[Path]:
    log.setLevel(logging.INFO)
    if not any(isinstance(h, logging.StreamHandler) for h in log.handlers):
        stream = logging.StreamHandler()
        stream.setLevel(logging.WARNING)
        log.addHandler(stream)
    if data_dir is None:
        return None
    try:
        logs = data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / "vmap.log"
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    return path


def _excepthook(exc_type, exc, tb) -> None:
    global _in_hook
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    log.error("Unhandled exception", exc_info=(exc_type, exc, tb))
    if _in_hook or QApplication.instance() is None:
        return
    _in_hook = True
    try:
        QMessageBox.critical(None, tr("Unexpected Error"), tr(
            "An unexpected error occurred. Your document is still open; please save your work."
            "\n\n{error}").format(error=f"{exc_type.__name__}: {exc}"))
    finally:
        _in_hook = False


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv if argv is None else argv) or [APP_NAME]
    if any(a in ("--version", "-V") for a in args[1:]):
        print(f"{APP_NAME} {__version__}")
        return 0
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or VMapApplication(args)

    from vmap.ui.context import AppContext
    from vmap.ui.icons import app_icon
    from vmap.ui.mainwindow import MainWindow

    app.setWindowIcon(app_icon())
    load_translations(app)
    data_dir = _data_dir()
    log_path = _setup_logging(data_dir)
    sys.excepthook = _excepthook
    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except (ValueError, OSError):
        pass
    ctx = AppContext.create(data_dir, log_path)
    log.info("starting %s %s", APP_NAME, __version__)
    window = MainWindow(ctx)
    window.show()
    files = [a for a in app.arguments()[1:] if not a.startswith("-")]
    if isinstance(app, VMapApplication):
        app.file_open_requested.connect(window.open_path)
        files += app.mark_ready()
    if files:
        QTimer.singleShot(0, lambda: window.open_path(files[0]))
    code = app.exec()
    ctx.db.close()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
