"""Find & replace bar for the current sheet (titles, optionally notes)."""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from vmap.core.commands import Command, MacroCommand, SetTopicAttrCommand
from vmap.core.model import Topic
from vmap.core.search import (SearchError, SearchOptions, compile_pattern, find_topics,
                              replace_text, topic_matches)
from vmap.i18n import tr
from vmap.ui.canvas.view import K_ENTER, K_RETURN, MapView, key_code


class FindBar(QFrame):
    closed = Signal()

    def __init__(self, view: MapView, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.update_count)

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText(tr("Find in topics"))
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setMaxLength(1000)
        self.find_edit.textChanged.connect(lambda _t: self._timer.start())
        self.find_edit.installEventFilter(self)
        self.case_btn = self._toggle("Aa", tr("Match case"))
        self.word_btn = self._toggle("W", tr("Whole words only"))
        self.regex_btn = self._toggle(".*", tr("Regular expression"))
        self.notes_btn = self._toggle("\u00b6", tr("Also search notes"))
        prev_btn = QToolButton()
        prev_btn.setArrowType(Qt.ArrowType.UpArrow)
        prev_btn.setToolTip(tr("Previous match (Shift+Enter)"))
        prev_btn.clicked.connect(self.find_prev)
        next_btn = QToolButton()
        next_btn.setArrowType(Qt.ArrowType.DownArrow)
        next_btn.setToolTip(tr("Next match (Enter)"))
        next_btn.clicked.connect(self.find_next)
        self.count_label = QLabel()
        self.count_label.setMinimumWidth(90)
        close_btn = QToolButton()
        close_btn.setText("\u2715")
        close_btn.setAutoRaise(True)
        close_btn.setToolTip(tr("Close (Esc)"))
        close_btn.clicked.connect(self.close_bar)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel(tr("Find:")))
        row1.addWidget(self.find_edit, 1)
        for w in (self.case_btn, self.word_btn, self.regex_btn, self.notes_btn,
                  prev_btn, next_btn, self.count_label, close_btn):
            row1.addWidget(w)

        self.replace_row = QWidget()
        row2 = QHBoxLayout(self.replace_row)
        row2.setContentsMargins(0, 0, 0, 0)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText(tr("Replace with"))
        self.replace_edit.setMaxLength(1000)
        self.replace_edit.returnPressed.connect(self.replace_current)
        replace_btn = QPushButton(tr("Replace"))
        replace_btn.clicked.connect(self.replace_current)
        replace_all_btn = QPushButton(tr("Replace All"))
        replace_all_btn.clicked.connect(self.replace_all)
        row2.addWidget(QLabel(tr("Replace:")))
        row2.addWidget(self.replace_edit, 1)
        row2.addWidget(replace_btn)
        row2.addWidget(replace_all_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        layout.addLayout(row1)
        layout.addWidget(self.replace_row)

        esc = QShortcut(QKeySequence("Esc"), self)
        esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.activated.connect(self.close_bar)
        view.selection_changed.connect(lambda: self._timer.start() if self.isVisible() else None)

    def _toggle(self, text: str, tip: str) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setCheckable(True)
        b.setAutoRaise(True)
        b.setToolTip(tip)
        b.toggled.connect(lambda _on: self.update_count())
        return b

    def eventFilter(self, obj, event) -> bool:
        if (obj is self.find_edit and event.type() == QEvent.Type.KeyPress
                and key_code(event) in (K_RETURN, K_ENTER)):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.find_prev()
            else:
                self.find_next()
            return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------- open/close
    def open_bar(self, replace: bool = False) -> None:
        self.replace_row.setVisible(replace)
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self.update_count()

    def close_bar(self) -> None:
        self.hide()
        self.closed.emit()

    def options(self) -> SearchOptions:
        return SearchOptions(self.find_edit.text(), self.case_btn.isChecked(),
                             self.word_btn.isChecked(), self.regex_btn.isChecked(),
                             self.notes_btn.isChecked())

    def _matches(self) -> tuple[list[Topic], Optional[str]]:
        sheet = self.view.sheet
        if sheet is None or not self.find_edit.text():
            return [], None
        try:
            return find_topics(sheet.root, self.options()), None
        except SearchError as exc:
            return [], str(exc)

    def _status(self, text: str, tip: str = "", warn: bool = False) -> None:
        self.count_label.setText(text)
        self.count_label.setToolTip(tip)
        self.count_label.setStyleSheet("color: #C62828;" if warn else "")

    def update_count(self) -> None:
        if not self.find_edit.text():
            self._status("")
            return
        matches, error = self._matches()
        if error:
            self._status(tr("Invalid pattern"), error, warn=True)
            return
        if not matches:
            self._status(tr("No matches"), warn=True)
            return
        current = self.view.current_topic()
        pos = next((i for i, m in enumerate(matches) if m is current), -1)
        if pos >= 0:
            self._status(tr("{i} of {n}").format(i=pos + 1, n=len(matches)))
        else:
            self._status(tr("{n} matches").format(n=len(matches)))

    # ------------------------------------------------------------- navigation
    def find_next(self) -> None:
        self._step(True)

    def find_prev(self) -> None:
        self._step(False)

    def _step(self, forward: bool) -> None:
        if not self.isVisible() or not self.find_edit.text():
            self.open_bar(self.replace_row.isVisible() and self.isVisible())
            if not self.find_edit.text():
                return
        sheet = self.view.sheet
        matches, _ = self._matches()
        if sheet is None or not matches:
            self.update_count()
            return
        order = {id(t): i for i, t in enumerate(sheet.root.iter_subtree())}
        current = self.view.current_topic()
        cur = order.get(id(current), -1) if current is not None else -1
        if forward:
            target = next((m for m in matches if order[id(m)] > cur), matches[0])
        else:
            target = next((m for m in reversed(matches) if order[id(m)] < cur), matches[-1])
        self._go_to(target)

    def _go_to(self, topic: Topic) -> None:
        self.view.finish_edit(commit=True)
        self.view.ops.reveal(topic)        # unfolds collapsed ancestors (one undo step)
        self.view.select_topics([topic])
        self.view.center_on_topic(topic)
        self.update_count()

    # ---------------------------------------------------------------- replace
    def _pattern(self) -> Optional["re.Pattern[str]"]:
        try:
            return compile_pattern(self.options())
        except SearchError as exc:
            self._status(tr("Invalid pattern"), str(exc), warn=True)
            return None

    def _replacements(self, topics: list[Topic], pattern) -> Optional[list[Command]]:
        opts = self.options()
        fields = ("title", "notes") if opts.include_notes else ("title",)
        repl = self.replace_edit.text()
        commands: list[Command] = []
        try:
            for t in topics:
                for attr in fields:
                    old = getattr(t, attr)
                    if not old:
                        continue
                    new, n = replace_text(old, pattern, repl, opts.regex)
                    if n and new != old:
                        commands.append(SetTopicAttrCommand(t, attr, new))
        except SearchError as exc:
            self._status(tr("Invalid replacement"), str(exc), warn=True)
            return None
        return commands

    def _run(self, command: Command) -> None:
        doc, sheet = self.view.document, self.view.sheet
        if doc is not None and sheet is not None:
            doc.execute(command, sheet)

    def replace_current(self) -> None:
        self.view.finish_edit(commit=True)
        pattern = self._pattern()
        if pattern is None:
            return
        current = self.view.current_topic()
        if current is None or not topic_matches(current, pattern, self.notes_btn.isChecked()):
            self.find_next()
            return
        commands = self._replacements([current], pattern)
        if commands:
            self._run(MacroCommand(tr("Replace"), commands))
        if commands is not None:
            self.find_next()

    def replace_all(self) -> None:
        self.view.finish_edit(commit=True)
        pattern = self._pattern()
        matches, _ = self._matches()
        if pattern is None:
            return
        commands = self._replacements(matches, pattern)
        if commands is None:
            return
        if not commands:
            self._status(tr("No matches"), warn=True)
            return
        self._run(MacroCommand(tr("Replace All"), commands))
        self.view.message.emit(tr("Replaced text in {n} field(s).").format(n=len(commands)))
        self.update_count()
