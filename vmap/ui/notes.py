"""Note hover balloon and the XMind-style note editor popup (F4, Insert > Note, note icon)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QKeySequence, QPainter, QPainterPath, QPen,
                           QTextCursor)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QSizeGrip,
                               QVBoxLayout, QWidget)

from vmap.core.model import Topic
from vmap.i18n import tr
from vmap.ui.canvas.items import is_rtl

if TYPE_CHECKING:
    from vmap.ui.canvas.view import MapView

MAX_NOTES_CHARS = 200_000   # same limit as the Properties panel


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def note_summary(text: str, max_chars: int = 600, max_lines: int = 12) -> tuple[str, bool]:
    """(summary, truncated) for the balloon: runs of blank lines collapsed, spaces tidied."""
    lines: list[str] = []
    blank = False
    for raw in (text or "").replace("\u2029", "\n").split("\n"):
        line = re.sub(r"[ \t\u00a0]+", " ", raw).strip()
        if not line:
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        blank = False
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    truncated = len(lines) > max_lines
    out = "\n".join(lines[:max_lines])
    if len(out) > max_chars:
        cut = out.rfind(" ", 0, max_chars)
        out = out[: cut if cut > max_chars * 0.6 else max_chars].rstrip()
        truncated = True
    return out, truncated


class NoteBalloon(QWidget):
    """Yellow balloon with a plain-text note summary. Never takes focus or clicks."""

    TAIL = 8
    MAX_W = 380

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        for attr in (Qt.WidgetAttribute.WA_TranslucentBackground,
                     Qt.WidgetAttribute.WA_ShowWithoutActivating,
                     Qt.WidgetAttribute.WA_TransparentForMouseEvents):
            self.setAttribute(attr, True)
        self._up, self._tail_x = True, 20.0
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(4)
        key = QKeySequence("F4").toString(QKeySequence.SequenceFormat.NativeText)
        self.title, self.body = QLabel(), QLabel()
        self.hint = QLabel(tr("Click the note icon or press {key} to edit").format(key=key))
        for label, css in ((self.title, "color: #3B3413; font-weight: 600;"),
                           (self.body, "color: #3B3413;"),
                           (self.hint, "color: #8A7D3C; font-size: 11px;")):
            label.setTextFormat(Qt.TextFormat.PlainText)   # notes are never rendered as HTML
            label.setStyleSheet(css)
            self._layout.addWidget(label)
        self.body.setWordWrap(True)

    def _set_tail(self, up: bool) -> None:
        self._up = up
        t = self.TAIL
        self._layout.setContentsMargins(12, 9 + (t if up else 0), 12, 9 + (0 if up else t))
        self.adjustSize()

    def show_for(self, title: str, summary: str, truncated: bool, below: QPoint,
                 above: QPoint) -> None:
        self.title.setText(_elide(tr("Note \u00b7 {title}").format(title=title), 70))
        self.body.setText(summary + ("\n\u2026" if truncated else ""))
        side = Qt.AlignmentFlag.AlignRight if is_rtl(summary) else Qt.AlignmentFlag.AlignLeft
        self.body.setAlignment(side | Qt.AlignmentFlag.AlignAbsolute)
        fm = self.body.fontMetrics()
        natural = max((fm.horizontalAdvance(line) for line in self.body.text().split("\n")),
                      default=0) + 6
        self.body.setFixedWidth(int(min(self.MAX_W, max(220, natural))))
        screen = QGuiApplication.screenAt(below) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        self._set_tail(True)
        x, y = below.x() - 24, below.y() + 2
        if y + self.height() > avail.bottom():
            self._set_tail(False)
            y = above.y() - self.height() - 2
        x = max(avail.left() + 4, min(x, avail.right() - self.width() - 4))
        self._tail_x = float(min(max(below.x() - x, 14), self.width() - 14))
        self.move(x, y)
        self.show()
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        t, x = float(self.TAIL), self._tail_x
        body = r.adjusted(0, t, 0, 0) if self._up else r.adjusted(0, 0, 0, -t)
        shape = QPainterPath()
        shape.addRoundedRect(body, 7, 7)
        tail = QPainterPath()
        if self._up:
            tail.moveTo(x - 7, body.top() + 1)
            tail.lineTo(x, r.top())
            tail.lineTo(x + 7, body.top() + 1)
        else:
            tail.moveTo(x - 7, body.bottom() - 1)
            tail.lineTo(x, r.bottom())
            tail.lineTo(x + 7, body.bottom() - 1)
        tail.closeSubpath()
        p.setPen(QPen(QColor("#D4B24C"), 1.0))
        p.setBrush(QColor("#FFF8C5"))
        p.drawPath(shape.united(tail))
        p.end()


def _key(event) -> int:
    key = event.key()
    return key.value if hasattr(key, "value") else int(key)


class NoteEditorPopup(QFrame):
    """Note editor that opens next to the topic. Esc, Ctrl+Enter or a click outside closes it
    and saves the note as one undoable command."""

    def __init__(self, parent: QWidget, on_commit: Callable[[Topic, str], None]) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._on_commit = on_commit
        self.topic: Optional[Topic] = None
        self._original = ""
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(tr("Write a note for this topic\u2026"))
        self.editor.installEventFilter(self)
        hint = QLabel(tr("Esc, Ctrl+Enter or a click outside closes and saves (Ctrl+Z undoes)."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid); font-size: 11px;")
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        bottom.addWidget(QSizeGrip(self), 0,
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 4)
        layout.addWidget(self.title)
        layout.addWidget(self.editor, 1)
        layout.addLayout(bottom)
        self.resize(420, 260)

    def open_for(self, view: "MapView", topic: Topic) -> bool:
        item = view.scene_.item_for(topic)
        if item is None:
            return False
        self.topic, self._original = topic, topic.notes
        title = topic.title.replace("\n", " ")
        self.title.setText(_elide(tr("Note \u00b7 {title}").format(title=title), 80))
        self.editor.setPlainText(topic.notes)
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        rect = view.mapFromScene(item.mapRectToScene(item.box_rect())).boundingRect()
        below = view.viewport().mapToGlobal(rect.bottomLeft()) + QPoint(0, 8)
        top = view.viewport().mapToGlobal(rect.topLeft()).y()
        screen = QGuiApplication.screenAt(below) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        x = max(avail.left() + 4, min(below.x(), avail.right() - self.width() - 4))
        y = below.y()
        if y + self.height() > avail.bottom():
            y = max(avail.top() + 4, top - 8 - self.height())
        self.move(x, y)
        self.show()
        self.activateWindow()
        self.editor.setFocus(Qt.FocusReason.PopupFocusReason)
        return True

    def eventFilter(self, obj, event) -> bool:
        if obj is self.editor and event.type() == QEvent.Type.KeyPress:
            key = _key(event)
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if key == Qt.Key.Key_Escape.value or (
                    ctrl and key in (Qt.Key.Key_Return.value, Qt.Key.Key_Enter.value)):
                self.close()
                return True
        return super().eventFilter(obj, event)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        topic, self.topic = self.topic, None
        if topic is not None:
            text = self.editor.toPlainText()[:MAX_NOTES_CHARS]
            if text != self._original:
                self._on_commit(topic, text)
