"""Translation helpers.

Every user-visible string goes through :func:`tr`, the single choke point for
translation (including RTL languages such as Persian and Arabic). The module
works without Qt so the core stays importable in headless tools and tests.
"""
from __future__ import annotations

from pathlib import Path

try:
    from PySide6.QtCore import QCoreApplication, QLocale, QTranslator
except ImportError:  # pragma: no cover - core used without Qt
    QCoreApplication = None  # type: ignore[assignment]

CONTEXT = "vmap"
TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"
_installed: list = []


def tr(text: str, context: str = CONTEXT) -> str:
    if QCoreApplication is None or QCoreApplication.instance() is None:
        return text
    return QCoreApplication.translate(context, text)


def load_translations(app) -> str | None:
    """Install vmap_<locale>.qm from vmap/translations if one exists."""
    if QCoreApplication is None:
        return None
    translator = QTranslator(app)
    if translator.load(QLocale.system(), "vmap", "_", str(TRANSLATIONS_DIR)):
        app.installTranslator(translator)
        _installed.append(translator)
        return QLocale.system().name()
    return None
