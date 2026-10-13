"""Properties panel (right dock): sheet settings, topic style overrides and notes.

Every change goes through a Command, so it is undoable. Text fields commit
when they lose focus (not per keystroke) to keep undo history meaningful.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
                               QFontComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)

from vmap.core.commands import SetSheetAttrCommand, SetStyleCommand, SetTopicAttrCommand
from vmap.core.document import Document
from vmap.core.model import Sheet, Topic
from vmap.i18n import tr
from vmap.mindmap.layouts import STRUCTURES
from vmap.themes.engine import (DEFAULT_STYLE, NUMERIC_RANGES, SHAPES, STYLE_KEYS,
                                ThemeRegistry, check_style_value)
from vmap.ui.canvas.view import MapView

SHAPE_NAMES = {"rounded_rect": "Rounded Rectangle", "rect": "Rectangle", "pill": "Pill",
               "ellipse": "Ellipse", "underline": "Underline"}
MAX_NOTES_CHARS = 200_000


def format_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return iso


class ColorButton(QToolButton):
    """Click = colour dialog; arrow menu = None / Theme Default."""
    picked = Signal(object)  # "#RRGGBB" | "none" | None (remove override)

    def __init__(self, title: str, allow_none: bool, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._color = "#FFFFFF"
        self.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setMinimumWidth(116)
        menu = QMenu(self)
        a = menu.addAction(tr("Choose Color\u2026"))
        a.triggered.connect(self._choose)
        if allow_none:
            a = menu.addAction(tr("None"))
            a.triggered.connect(lambda: self.picked.emit("none"))
        a = menu.addAction(tr("Theme Default"))
        a.triggered.connect(lambda: self.picked.emit(None))
        self.setMenu(menu)
        self.clicked.connect(self._choose)

    def set_color(self, value: str) -> None:
        self._color = value
        pm = QPixmap(16, 16)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setPen(QPen(QColor("#808080"), 1))
        if value == "none":
            p.setBrush(QColor("#FFFFFF"))
            p.drawRect(0, 0, 15, 15)
            p.setPen(QPen(QColor("#D32F2F"), 1.5))
            p.drawLine(1, 14, 14, 1)
        else:
            p.setBrush(QColor(value))
            p.drawRect(0, 0, 15, 15)
        p.end()
        self.setIcon(QIcon(pm))
        self.setText(tr("None") if value == "none" else value.upper())

    def _choose(self) -> None:
        initial = QColor(self._color) if self._color != "none" else QColor("#FFFFFF")
        color = QColorDialog.getColor(initial, self, self._title)
        if color.isValid():
            self.picked.emit(color.name().upper())


class NotesEdit(QPlainTextEdit):
    editing_finished = Signal()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self.editing_finished.emit()


class InspectorPanel(QScrollArea):
    def __init__(self, view: MapView, themes: ThemeRegistry, parent=None) -> None:
        super().__init__(parent)
        self.view, self.themes = view, themes
        self.document: Optional[Document] = None
        self._updating = False
        self._notes_topic: Optional[Topic] = None
        self._notes_dirty = False
        self._title_sheet: Optional[Sheet] = None
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setMinimumWidth(240)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 8, 8, 8)

        box = QGroupBox(tr("Sheet"))
        form = QFormLayout(box)
        self.sheet_title = QLineEdit()
        self.sheet_title.setMaxLength(200)
        self.sheet_title.editingFinished.connect(self._commit_sheet_title)
        self.theme_combo = QComboBox()
        self.theme_combo.activated.connect(self._on_theme)
        self.structure_combo = QComboBox()
        for sid, name in STRUCTURES.items():
            self.structure_combo.addItem(tr(name), sid)
        self.structure_combo.activated.connect(self._on_structure)
        form.addRow(tr("Title:"), self.sheet_title)
        form.addRow(tr("Theme:"), self.theme_combo)
        form.addRow(tr("Structure:"), self.structure_combo)
        layout.addWidget(box)

        self.style_box = QGroupBox(tr("Topic Style"))
        form = QFormLayout(self.style_box)
        self.shape_combo = QComboBox()
        for shape in SHAPES:
            self.shape_combo.addItem(tr(SHAPE_NAMES.get(shape, shape)), shape)
        self.shape_combo.activated.connect(
            lambda i: self._set_style("shape", self.shape_combo.itemData(i)))
        self.colors: dict[str, ColorButton] = {}
        for key, title, allow_none in (("fill", tr("Fill"), True), ("border", tr("Border"), True),
                                       ("text_color", tr("Text Color"), False),
                                       ("line_color", tr("Branch Line"), True)):
            btn = ColorButton(title, allow_none)
            btn.picked.connect(lambda value, k=key: self._set_style(k, value))
            self.colors[key] = btn
        self.font_combo = QFontComboBox()
        self.font_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font_combo.setMinimumContentsLength(10)
        self.font_combo.currentFontChanged.connect(self._on_font)
        self.font_size = self._spin(*NUMERIC_RANGES["font_size"], 1.0, 1, "font_size")
        self.border_width = self._spin(*NUMERIC_RANGES["border_width"], 0.5, 1, "border_width")
        self.bold = QCheckBox(tr("Bold"))
        self.bold.toggled.connect(lambda on: self._set_style("bold", bool(on)))
        self.italic = QCheckBox(tr("Italic"))
        self.italic.toggled.connect(lambda on: self._set_style("italic", bool(on)))
        emphasis = QHBoxLayout()
        emphasis.addWidget(self.bold)
        emphasis.addWidget(self.italic)
        emphasis.addStretch(1)
        self.reset_btn = QPushButton(tr("Reset to Theme Style"))
        self.reset_btn.clicked.connect(self._reset_style)
        form.addRow(tr("Shape:"), self.shape_combo)
        form.addRow(tr("Fill:"), self.colors["fill"])
        form.addRow(tr("Border:"), self.colors["border"])
        form.addRow(tr("Border width:"), self.border_width)
        form.addRow(tr("Font:"), self.font_combo)
        form.addRow(tr("Size:"), self.font_size)
        form.addRow("", emphasis)
        form.addRow(tr("Text:"), self.colors["text_color"])
        form.addRow(tr("Branch line:"), self.colors["line_color"])
        form.addRow(self.reset_btn)
        layout.addWidget(self.style_box)

        self.notes_box = QGroupBox(tr("Notes"))
        v = QVBoxLayout(self.notes_box)
        self.notes = NotesEdit()
        self.notes.setPlaceholderText(tr("Notes for the selected topic\u2026"))
        self.notes.setMinimumHeight(120)
        self.notes.textChanged.connect(self._on_notes_changed)
        self.notes.editing_finished.connect(self._commit_notes)
        v.addWidget(self.notes)
        layout.addWidget(self.notes_box)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.info)
        layout.addStretch(1)
        self.setWidget(body)
        for w in (self.theme_combo, self.structure_combo, self.shape_combo, self.font_combo,
                  self.font_size, self.border_width):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            w.installEventFilter(self)

    def _spin(self, lo: float, hi: float, step: float, decimals: int, key: str) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setDecimals(decimals)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(lambda value, k=key: self._set_style(k, float(value)))
        return s

    def eventFilter(self, obj, event) -> bool:
        # Scrolling the panel must not silently change combo/spin values.
        if event.type() == QEvent.Type.Wheel and isinstance(obj, QWidget) and not obj.hasFocus():
            self.wheelEvent(event)
            return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ state
    def set_document(self, document: Document) -> None:
        self.document = document
        self._notes_topic = None
        self._notes_dirty = False
        self._title_sheet = None
        self._updating = True
        try:
            self.notes.setPlainText("")
        finally:
            self._updating = False

    def commit_pending(self) -> None:
        self._commit_sheet_title()
        self._commit_notes()

    def focus_notes(self) -> None:
        if self.notes_box.isEnabled():
            self.notes.setFocus()
            self.notes.moveCursor(QTextCursor.MoveOperation.End)

    def _sync_theme_combo(self, theme_id: str) -> None:
        wanted = [(t.name, t.id) for t in self.themes.all()]
        if theme_id not in self.themes:
            wanted.insert(0, (tr("{id} (not installed)").format(id=theme_id), theme_id))
        combo = self.theme_combo
        current = [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]
        if current != wanted:
            combo.clear()
            for name, tid in wanted:
                combo.addItem(name, tid)
        combo.setCurrentIndex(combo.findData(theme_id))

    def refresh(self) -> None:
        self._commit_notes()
        sheet = self.view.sheet
        self._updating = True
        try:
            if sheet is None or self.document is None:
                self.setEnabled(False)
                return
            self.setEnabled(True)
            if sheet is not self._title_sheet or not (self.sheet_title.hasFocus()
                                                      and self.sheet_title.isModified()):
                self._title_sheet = sheet
                self.sheet_title.setText(sheet.title)
            self._sync_theme_combo(sheet.theme_id)
            self.structure_combo.setCurrentIndex(self.structure_combo.findData(sheet.structure))

            topics = self.view.selected_topics()
            self.style_box.setEnabled(bool(topics))
            if topics:
                style: dict[str, Any] = self.view.scene_.style_for(topics[0]) or dict(DEFAULT_STYLE)
                self.shape_combo.setCurrentIndex(self.shape_combo.findData(style["shape"]))
                for key, btn in self.colors.items():
                    btn.set_color(style[key])
                family = style["font_family"] or QApplication.font().family()
                self.font_combo.setCurrentFont(QFont(family))
                self.font_size.setValue(float(style["font_size"]))
                self.border_width.setValue(float(style["border_width"]))
                self.bold.setChecked(bool(style["bold"]))
                self.italic.setChecked(bool(style["italic"]))
                self.reset_btn.setEnabled(any(k in t.style for t in topics for k in STYLE_KEYS))

            single = topics[0] if len(topics) == 1 else None
            if single is not self._notes_topic:
                self._notes_topic = single
                self.notes.setPlainText(single.notes if single else "")
                self._notes_dirty = False
            elif single is not None and not self._notes_dirty and self.notes.toPlainText() != single.notes:
                self.notes.setPlainText(single.notes)
            self.notes_box.setEnabled(single is not None)

            if single is not None:
                self.info.setText(tr("Created: {c}\nModified: {m}").format(
                    c=format_time(single.created), m=format_time(single.modified)))
            elif topics:
                self.info.setText(tr("{n} topics selected").format(n=len(topics)))
            else:
                self.info.setText(tr("No topic selected"))
        finally:
            self._updating = False

    # --------------------------------------------------------------- commits
    def _exec(self, command, sheet=None) -> None:
        if self.document is None:
            return
        self.view.finish_edit(commit=True)
        try:
            self.document.execute(command, sheet or self.view.sheet)
        except ValueError as exc:
            self.view.message.emit(str(exc))

    def _commit_sheet_title(self) -> None:
        if self._updating or not self.sheet_title.isModified():
            return
        self.sheet_title.setModified(False)
        sheet, text = self._title_sheet, self.sheet_title.text().strip()
        if (sheet is None or self.document is None or sheet not in self.document.workbook.sheets
                or not text or text == sheet.title):
            return
        self._exec(SetSheetAttrCommand(sheet, "title", text, label=tr("Rename Sheet")), sheet)

    def _on_notes_changed(self) -> None:
        if not self._updating:
            self._notes_dirty = True

    def _commit_notes(self) -> None:
        if not self._notes_dirty:
            return
        self._notes_dirty = False
        topic = self._notes_topic
        if topic is None or self.document is None or not self.view.in_sheet(topic):
            return
        text = self.notes.toPlainText()[:MAX_NOTES_CHARS]
        if text != topic.notes:
            self._exec(SetTopicAttrCommand(topic, "notes", text, label=tr("Edit Note")))

    def _on_theme(self, index: int) -> None:
        tid, sheet = self.theme_combo.itemData(index), self.view.sheet
        if sheet is not None and tid and tid != sheet.theme_id and tid in self.themes:
            self._exec(SetSheetAttrCommand(sheet, "theme_id", tid, label=tr("Change Theme")))

    def _on_structure(self, index: int) -> None:
        sid, sheet = self.structure_combo.itemData(index), self.view.sheet
        if sheet is not None and sid in STRUCTURES and sid != sheet.structure:
            self._exec(SetSheetAttrCommand(sheet, "structure", sid, label=tr("Change Structure")))

    def _on_font(self, font: QFont) -> None:
        self._set_style("font_family", font.family())

    def _set_style(self, key: str, value: Any) -> None:
        if self._updating or self.document is None:
            return
        topics = self.view.selected_topics()
        if not topics:
            return
        if value is not None:
            try:
                value = check_style_value(key, value)
            except ValueError:
                return
        if all(t.style.get(key) == value for t in topics):
            return
        self._exec(SetStyleCommand(topics, {key: value}, label=tr("Change Style")))

    def _reset_style(self) -> None:
        topics = [t for t in self.view.selected_topics() if any(k in t.style for k in STYLE_KEYS)]
        if topics:
            self._exec(SetStyleCommand(topics, {k: None for k in STYLE_KEYS},
                                       label=tr("Reset Style")))
