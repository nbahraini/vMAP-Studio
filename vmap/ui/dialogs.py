"""Dialogs: preferences, PNG options, reports, shortcuts, diagnostics, properties, about."""
from __future__ import annotations

import platform
from typing import TYPE_CHECKING

import PySide6
from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from vmap import APP_NAME, __version__
from vmap.core.document import Document
from vmap.formats.base import ConversionReport, FormatRegistry
from vmap.i18n import tr
from vmap.mindmap.layouts import DEFAULT_STRUCTURE, STRUCTURES
from vmap.themes.engine import ThemeRegistry
from vmap.ui.inspector import format_time

if TYPE_CHECKING:
    from vmap.ui.context import AppContext

TOOLBAR_STYLES = {"text_under": "Icons with text below", "text_beside": "Icons with text beside",
                  "icons": "Icons only"}
MAX_REPORT_LINES = 25


def _buttons(dialog: QDialog, cancel: bool = True) -> QDialogButtonBox:
    std = QDialogButtonBox.StandardButton
    box = QDialogButtonBox(std.Ok | std.Cancel if cancel else std.Close)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def _select(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def show_report(parent, title: str, report: ConversionReport) -> None:
    lines = report.summary().splitlines()
    icon = QMessageBox.Icon.Information if report.lossless else QMessageBox.Icon.Warning
    box = QMessageBox(icon, title, report.compatibility, QMessageBox.StandardButton.Ok, parent)
    body = lines[1:MAX_REPORT_LINES + 1]
    if len(lines) > MAX_REPORT_LINES + 1:
        body.append("\u2026")
        box.setDetailedText(report.summary())
    box.setInformativeText("\n".join(body))
    box.exec()


class PreferencesDialog(QDialog):
    def __init__(self, parent, themes: ThemeRegistry, values: dict[str, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Preferences"))
        self.theme = QComboBox()
        for t in themes.all():
            self.theme.addItem(t.name, t.id)
        _select(self.theme, values.get("default_theme"))
        self.structure = QComboBox()
        for sid, name in STRUCTURES.items():
            self.structure.addItem(tr(name), sid)
        _select(self.structure, values.get("default_structure"))
        self.undo = QSpinBox()
        self.undo.setRange(0, 100_000)
        self.undo.setSpecialValueText(tr("Unlimited"))
        self.undo.setValue(int(values.get("undo_limit", "0")))
        self.toolbar = QComboBox()
        for key, name in TOOLBAR_STYLES.items():
            self.toolbar.addItem(tr(name), key)
        _select(self.toolbar, values.get("toolbar_style"))
        form = QFormLayout()
        form.addRow(tr("Default theme for new maps:"), self.theme)
        form.addRow(tr("Default structure:"), self.structure)
        form.addRow(tr("Undo history limit:"), self.undo)
        form.addRow(tr("Toolbar buttons:"), self.toolbar)
        note = QLabel(tr("Theme and structure defaults apply to new workbooks and sheets."))
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(_buttons(self))

    def values(self) -> dict[str, str]:
        return {"default_theme": self.theme.currentData() or "classic",
                "default_structure": self.structure.currentData() or DEFAULT_STRUCTURE,
                "undo_limit": str(self.undo.value()),
                "toolbar_style": self.toolbar.currentData() or "text_under"}


class PngOptionsDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Export PNG Image"))
        self.scale = QComboBox()
        for s in (1, 2, 3, 4):
            self.scale.addItem(f"{s}\u00d7", s)
        self.scale.setCurrentIndex(1)
        self.transparent = QCheckBox(tr("Transparent background"))
        form = QFormLayout(self)
        form.addRow(tr("Resolution:"), self.scale)
        form.addRow("", self.transparent)
        form.addRow(_buttons(self))

    def values(self) -> tuple[float, bool]:
        return float(self.scale.currentData()), self.transparent.isChecked()


class ShortcutsDialog(QDialog):
    def __init__(self, parent, rows: list[tuple[str, str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Keyboard Shortcuts"))
        self.resize(580, 540)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Filter\u2026"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.rows = rows
        self.table = QTableWidget(len(rows), 2)
        self.table.setHorizontalHeaderLabels([tr("Action"), tr("Keys")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for r, (name, keys) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(keys))
        note = QLabel(tr("Customisable shortcuts are planned (see ROADMAP.md)."))
        layout = QVBoxLayout(self)
        layout.addWidget(self.filter)
        layout.addWidget(self.table)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, cancel=False))

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold()
        for r, (name, keys) in enumerate(self.rows):
            self.table.setRowHidden(r, bool(needle) and needle not in f"{name} {keys}".casefold())


class TextReportDialog(QDialog):
    def __init__(self, parent, title: str, text: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 420)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        buttons = _buttons(self, cancel=False)
        copy = buttons.addButton(tr("Copy to Clipboard"), QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
        layout = QVBoxLayout(self)
        layout.addWidget(view)
        layout.addWidget(buttons)


class DocumentPropertiesDialog(QDialog):
    def __init__(self, parent, document: Document) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Document Properties"))
        wb = document.workbook
        rows = [(tr("File:"), str(document.path) if document.path else tr("Not saved yet")),
                (tr("Sheets:"), str(len(wb.sheets))),
                (tr("Topics:"), str(wb.topic_count())),
                (tr("Created:"), format_time(wb.created)),
                (tr("Modified:"), format_time(wb.modified)),
                (tr("Workbook ID:"), wb.id)]
        form = QFormLayout(self)
        for label, value in rows:
            field = QLabel(value)
            field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            field.setWordWrap(True)
            form.addRow(label, field)
        form.addRow(_buttons(self, cancel=False))


def diagnostics_text(ctx: "AppContext", formats: FormatRegistry) -> str:
    screen = QGuiApplication.primaryScreen()
    lines = [f"{APP_NAME} {__version__}",
             f"Python {platform.python_version()} ({platform.python_implementation()})",
             f"PySide6 {PySide6.__version__}, Qt runtime {qVersion()}",
             f"OS: {platform.platform()} [{platform.machine()}]",
             f"Qt platform plugin: {QGuiApplication.platformName()}",
             f"Screen scale: {screen.devicePixelRatio() if screen else '?'}",
             f"Data directory: {ctx.data_dir or '-'}",
             f"Log file: {ctx.log_path or '-'}",
             f"Themes: {', '.join(t.id for t in ctx.themes.all())}",
             f"File formats: {', '.join(a.name for a in formats.all())}"]
    if ctx.warnings:
        lines += ["", "Startup warnings:"] + [f"  - {w}" for w in ctx.warnings]
    else:
        lines.append("Startup warnings: none")
    return "\n".join(lines)


def show_about(parent) -> None:
    QMessageBox.about(parent, tr("About {app}").format(app=APP_NAME), tr(
        "<h3>{app} {version}</h3>"
        "<p>Modular, cross-platform mind mapping and visual thinking.</p>"
        "<p>Phase 1 build. See ROADMAP.md for implemented and planned features.</p>"
        "<p>An independent implementation, not affiliated with or endorsed by XMind Ltd. "
        "or any other mind-mapping vendor.</p>"
        "<p>Python {py} \u00b7 PySide6 {pyside} \u00b7 Qt {qt}</p>").format(
        app=APP_NAME, version=__version__, py=platform.python_version(),
        pyside=PySide6.__version__, qt=qVersion()))
