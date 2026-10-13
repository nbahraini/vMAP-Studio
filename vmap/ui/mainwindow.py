"""Main window: menus, toolbar, docks, sheet tabs, status bar and file workflow.

Canvas keys (Tab, Enter, Delete, Space, arrows, Ctrl+/, Alt+Up/Down, Home) are
handled by MapView.keyPressEvent, never as window shortcuts, so they cannot be
stolen from text fields. Menus show them as hints only.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QByteArray, QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPalette
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QSpinBox, QTabBar, QTextEdit, QToolBar,
                               QToolButton, QVBoxLayout, QWidget)

from vmap import APP_NAME
from vmap.core.commands import (AddSheetCommand, Command, RemoveSheetCommand, SetSheetAttrCommand,
                                SetTopicAttrCommand)
from vmap.core.document import Document
from vmap.core.model import ROOT, Sheet, Workbook, clone_topic, new_sheet
from vmap.formats import FormatError, default_registry
from vmap.i18n import tr
from vmap.mindmap.layouts import DEFAULT_STRUCTURE, STRUCTURES
from vmap.ui.canvas.view import MapView
from vmap.ui.context import AppContext, read_theme_file
from vmap.ui.dialogs import (DocumentPropertiesDialog, PngOptionsDialog, PreferencesDialog,
                             ShortcutsDialog, TextReportDialog, diagnostics_text, show_about,
                             show_report)
from vmap.ui.export import export_png, export_svg
from vmap.ui.findbar import FindBar
from vmap.ui.icons import make_icon
from vmap.ui.inspector import InspectorPanel
from vmap.ui.markers import (EMBED_KEY, MarkerController, MarkerLibrary, MarkersPanel,
                             embed_custom_markers)
from vmap.ui.navigator import NavigatorWidget
from vmap.ui.notes import NoteEditorPopup
from vmap.ui.tasks import run_in_background

log = logging.getLogger(__name__)
IS_MAC = sys.platform == "darwin"
STATE_VERSION = 1
NATIVE = QKeySequence.SequenceFormat.NativeText
TOOLBAR_STYLE_MAP = {"text_under": Qt.ToolButtonStyle.ToolButtonTextUnderIcon,
                     "text_beside": Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
                     "icons": Qt.ToolButtonStyle.ToolButtonIconOnly}
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
YES = QMessageBox.StandardButton.Yes


def _native(keys: str) -> str:
    return QKeySequence(keys).toString(NATIVE)


def _same_file(a: Path | str, b: Path | str) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def _safe_name(name: str, fallback: str) -> str:
    return _UNSAFE_NAME.sub("_", name).strip(" .")[:120] or fallback


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.formats = default_registry()
        self.document: Optional[Document] = None
        self._icon_actions: list[tuple[QAction, str]] = []
        self._all_actions: list[QAction] = []
        self._theme_group: Optional[QActionGroup] = None
        self._sheet_index = 0
        self._doc_version = 0
        self._count_cache: tuple = (None, -1, 0)
        self._lossy_source: Optional[Path] = None
        self._busy = False
        self._zen = False
        self._zen_state: dict[str, bool] = {}
        self._was_maximized = False

        self.view = MapView(ctx.themes, self)
        self.view.set_grid(self._pref("view/grid") == "1")
        self.findbar = FindBar(self.view, self)
        self.findbar.hide()
        self.inspector = InspectorPanel(self.view, ctx.themes, self)
        self.navigator = NavigatorWidget(self.view, self)
        markers_dir = ctx.data_dir / "markers" if ctx.data_dir is not None else None
        self.marker_library = MarkerLibrary(markers_dir, self)
        ctx.warnings.extend(self.marker_library.load())
        self.view.scene_.marker_library = self.marker_library
        self.markers = MarkerController(self.view, self.marker_library, self._exec, self)
        self.note_popup = NoteEditorPopup(self, self._commit_note_popup)
        self._build_central()
        self._build_docks()
        self._build_actions()
        self._build_toolbar()
        self._build_menus()
        self._build_statusbar()
        self._build_hint()
        self._connect_signals()
        self._apply_icons()
        self._apply_toolbar_style()
        self._set_document(Document(self._new_workbook(), undo_limit=self._undo_limit()))
        self._restore_window_state()

    # ================================================================ settings
    def _pref(self, key: str, default: str = "") -> str:
        try:
            value = self.ctx.db.get(key)
        except sqlite3.Error:
            return default
        return default if value is None else value

    def _store(self, key: str, value: Any) -> None:
        try:
            self.ctx.db.set(key, value)
        except sqlite3.Error as exc:
            log.warning("could not store setting %s: %s", key, exc)

    def _undo_limit(self) -> int:
        try:
            return max(0, int(self._pref("pref/undo_limit", "0")))
        except ValueError:
            return 0

    def _apply_sheet_defaults(self, sheet: Sheet) -> Sheet:
        theme = self._pref("pref/default_theme", "classic")
        sheet.theme_id = theme if theme in self.ctx.themes else "classic"
        structure = self._pref("pref/default_structure", DEFAULT_STRUCTURE)
        sheet.structure = structure if structure in STRUCTURES else DEFAULT_STRUCTURE
        return sheet

    def _new_workbook(self) -> Workbook:
        wb = Workbook.new_default()
        self._apply_sheet_defaults(wb.sheets[0])
        return wb

    # ================================================================ building
    def _build_central(self) -> None:
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.view, 1)
        v.addWidget(self.findbar)
        self.bottom_bar = QWidget()
        h = QHBoxLayout(self.bottom_bar)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(2)
        self.tabs = QTabBar()
        self.tabs.setDocumentMode(True)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabBarDoubleClicked.connect(self._rename_sheet)
        self.tabs.customContextMenuRequested.connect(self._tab_menu)
        add = QToolButton()
        add.setText("+")
        add.setAutoRaise(True)
        add.setToolTip(tr("New Sheet"))
        add.clicked.connect(self._new_sheet)
        h.addWidget(self.tabs)
        h.addWidget(add)
        h.addStretch(1)
        v.addWidget(self.bottom_bar)
        self.setCentralWidget(central)

    def _build_docks(self) -> None:
        self.props_dock = QDockWidget(tr("Properties"), self)
        self.props_dock.setObjectName("propertiesDock")
        self.props_dock.setWidget(self.inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.props_dock)
        self.nav_dock = QDockWidget(tr("Overview"), self)
        self.nav_dock.setObjectName("navigatorDock")
        self.nav_dock.setWidget(self.navigator)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.nav_dock)
        self.markers_dock = MarkersPanel(self.markers, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.markers_dock)
        self.tabifyDockWidget(self.props_dock, self.markers_dock)
        self.props_dock.raise_()

    def _action(self, text: str, slot: Callable, shortcut=None, icon: Optional[str] = None, *,
                hint: tuple[str, ...] = (), icon_text: Optional[str] = None,
                checkable: bool = False) -> QAction:
        label = text.replace("&", "")
        if hint and not IS_MAC:
            text = f"{text}\t{' / '.join(_native(k) for k in hint)}"
        a = QAction(text, self)
        if checkable:
            a.setCheckable(True)
            a.toggled.connect(slot)
        else:
            a.triggered.connect(lambda checked=False, fn=slot: fn())
        if isinstance(shortcut, QKeySequence.StandardKey):
            a.setShortcuts(shortcut)
        elif isinstance(shortcut, (list, tuple)):
            a.setShortcuts([QKeySequence(s) for s in shortcut])
        elif shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if icon:
            self._icon_actions.append((a, icon))
        if icon_text:
            a.setIconText(icon_text)
        key = _native(hint[0]) if hint else a.shortcut().toString(NATIVE)
        a.setToolTip(f"{icon_text or label} ({key})" if key else (icon_text or label))
        a.setProperty("vmap_label", label)
        self.addAction(a)  # shortcuts keep working when the menu bar is hidden (Zen Mode)
        self._all_actions.append(a)
        return a

    def _build_actions(self) -> None:
        A, ops, view, S = self._action, self.view.ops, self.view, QKeySequence.StandardKey
        # File
        self.a_new = A(tr("&New Workbook"), self.new_document, S.New, "new", icon_text=tr("New"))
        self.a_open = A(tr("&Open\u2026"), self.open_dialog, S.Open, "open", icon_text=tr("Open"))
        self.a_save = A(tr("&Save"), self.save, S.Save, "save", icon_text=tr("Save"))
        self.a_save_as = A(tr("Save &As\u2026"), self.save_as, "Ctrl+Shift+S")
        self.a_save_copy = A(tr("Save a &Copy\u2026"), self.save_copy)
        self.a_export_png = A(tr("Sheet as &PNG Image\u2026"), lambda: self.export_image("png"))
        self.a_export_svg = A(tr("Sheet as S&VG Image\u2026"), lambda: self.export_image("svg"))
        self.a_props = A(tr("Document P&roperties\u2026"), self.show_properties)
        self.a_prefs = A(tr("&Preferences\u2026"), self.show_preferences, S.Preferences)
        self.a_prefs.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.a_quit = A(tr("&Quit"), self.close, S.Quit)
        self.a_quit.setMenuRole(QAction.MenuRole.QuitRole)
        # Edit
        self.a_undo = A(tr("&Undo"), self._undo, S.Undo, "undo", icon_text=tr("Undo"))
        self.a_redo = A(tr("&Redo"), self._redo, S.Redo, "redo", icon_text=tr("Redo"))
        self.a_cut = A(tr("Cu&t"), lambda: self._edit_cmd("cut", ops.cut), S.Cut)
        self.a_copy = A(tr("&Copy"), lambda: self._edit_cmd("copy", ops.copy), S.Copy)
        self.a_paste = A(tr("&Paste"), lambda: self._edit_cmd("paste", ops.paste), S.Paste)
        self.a_duplicate = A(tr("D&uplicate"), lambda: self._edit_cmd(None, ops.duplicate), "Ctrl+D")
        self.a_delete = A(tr("&Delete"), ops.delete_selected, None, "delete", hint=("Del",),
                          icon_text=tr("Delete"))
        self.a_select_all = A(tr("Select &All"), lambda: self._edit_cmd("selectAll", ops.select_all),
                              S.SelectAll)
        self.a_edit_topic = A(tr("&Edit Topic Text"), self._edit_current, hint=("F2", "Space"))
        self.a_find = A(tr("&Find\u2026"), lambda: self.findbar.open_bar(False), S.Find, "find",
                        icon_text=tr("Find"))
        self.a_replace = A(tr("R&eplace\u2026"), lambda: self.findbar.open_bar(True), S.Replace)
        self.a_find_next = A(tr("Find &Next"), self.findbar.find_next, S.FindNext)
        self.a_find_prev = A(tr("Find Pre&vious"), self.findbar.find_prev, S.FindPrevious)
        # Insert
        self.a_topic = A(tr("&Topic"), ops.add_sibling, None, "topic", hint=("Return",),
                         icon_text=tr("Topic"))
        self.a_topic_before = A(tr("Topic &Before"), lambda: ops.add_sibling(before=True),
                                hint=("Shift+Return",))
        self.a_subtopic = A(tr("&Subtopic"), ops.add_subtopic, None, "subtopic", hint=("Tab",),
                            icon_text=tr("Subtopic"))
        self.a_parent = A(tr("&Parent Topic"), ops.add_parent, hint=("Ctrl+Return",))
        self.a_note = A(tr("&Note\u2026"), self._edit_note, "F4")
        self.a_priority = [A(tr("Priority {n} Marker").format(n=n),
                             lambda n=n: self.markers.toggle(f"priority-{n}"), f"Ctrl+{n}")
                           for n in range(1, 10)]
        self.a_clear_markers = A(tr("Remove All Markers"), lambda: self.markers.clear())
        # View
        self.a_zoom_in = A(tr("Zoom &In"), view.zoom_in, ["Ctrl++", "Ctrl+="], "zoom_in",
                           icon_text=tr("Zoom In"))
        self.a_zoom_out = A(tr("Zoom &Out"), view.zoom_out, ["Ctrl+-"], "zoom_out",
                            icon_text=tr("Zoom Out"))
        self.a_actual = A(tr("&Actual Size"), view.actual_size, "Ctrl+0")
        self.a_fit = A(tr("&Fit Map"), view.fit_map, "Ctrl+Shift+F", "fit", icon_text=tr("Fit"))
        self.a_center = A(tr("Go to &Central Topic"), self._go_root, hint=("Home",))
        self.a_full_screen = A(tr("F&ull Screen"), self._set_full_screen, S.FullScreen,
                               checkable=True)
        self.a_zen = A(tr("&Zen Mode"), self._set_zen, "Ctrl+Shift+M", checkable=True)
        self.a_grid = A(tr("Show &Grid"), self._set_grid, checkable=True)
        self.a_grid.setChecked(self.view.show_grid)
        # Map
        self.a_fold = A(tr("&Fold / Unfold"), ops.toggle_fold, None, "fold", hint=("Ctrl+/",),
                        icon_text=tr("Fold"))
        self.a_expand_all = A(tr("&Expand All"), ops.expand_all)
        self.a_collapse_all = A(tr("&Collapse All"), ops.collapse_all)
        self.a_move_up = A(tr("Move Topic &Up"), lambda: ops.move_sibling(-1), hint=("Alt+Up",))
        self.a_move_down = A(tr("Move Topic Do&wn"), lambda: ops.move_sibling(1), hint=("Alt+Down",))
        self.a_sort_az = A(tr("Sort Subtopics A\u2192Z"), ops.sort_children)
        self.a_sort_za = A(tr("Sort Subtopics Z\u2192A"), lambda: ops.sort_children(reverse=True))
        self.a_new_sheet = A(tr("&New Sheet"), self._new_sheet, "Ctrl+T")
        self.a_rename_sheet = A(tr("&Rename Sheet\u2026"), lambda: self._rename_sheet(self._sheet_index))
        self.a_duplicate_sheet = A(tr("Duplicate S&heet"),
                                   lambda: self._duplicate_sheet(self._sheet_index))
        self.a_delete_sheet = A(tr("Delete Shee&t"), lambda: self._delete_sheet(self._sheet_index))
        self.a_import_theme = A(tr("&Import Theme\u2026"), self.import_theme)
        self.a_export_theme = A(tr("&Export Current Theme\u2026"), self.export_theme)
        # Help
        self.a_shortcuts = A(tr("&Keyboard Shortcuts"), self.show_shortcuts, S.HelpContents)
        self.a_diagnostics = A(tr("&Diagnostics\u2026"), self.show_diagnostics)
        self.a_about = A(tr("&About {app}").format(app=APP_NAME), lambda: show_about(self))
        self.a_about.setMenuRole(QAction.MenuRole.AboutRole)

        self.structure_menu = QMenu(tr("&Structure"), self)
        self.structure_group = QActionGroup(self)
        for sid, name in STRUCTURES.items():
            a = QAction(tr(name), self)
            a.setCheckable(True)
            a.setData(sid)
            a.triggered.connect(lambda checked=False, s=sid: self._set_sheet_attr(
                "structure", s, tr("Change Structure")))
            self.structure_group.addAction(a)
            self.structure_menu.addAction(a)
        self.structure_menu.menuAction().setIconText(tr("Structure"))
        self._icon_actions.append((self.structure_menu.menuAction(), "structure"))
        self.theme_menu = QMenu(tr("T&heme"), self)
        self.theme_menu.aboutToShow.connect(self._fill_theme_menu)
        self.theme_menu.menuAction().setIconText(tr("Theme"))
        self._icon_actions.append((self.theme_menu.menuAction(), "theme"))

    def _build_toolbar(self) -> None:
        tb = QToolBar(tr("Main Toolbar"), self)
        tb.setObjectName("mainToolbar")
        tb.setIconSize(QSize(20, 20))
        groups = ((self.a_new, self.a_open, self.a_save), (self.a_undo, self.a_redo),
                  (self.a_topic, self.a_subtopic, self.a_delete, self.a_fold),
                  (self.structure_menu.menuAction(), self.theme_menu.menuAction()),
                  (self.a_zoom_out, self.a_zoom_in, self.a_fit), (self.a_find,))
        for i, group in enumerate(groups):
            if i:
                tb.addSeparator()
            tb.addActions(list(group))
        for menu in (self.structure_menu, self.theme_menu):
            button = tb.widgetForAction(menu.menuAction())
            if isinstance(button, QToolButton):
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self.toolbar = tb

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        m.addActions([self.a_new, self.a_open])
        self.recent_menu = m.addMenu(tr("Open &Recent"))
        self.recent_menu.setToolTipsVisible(True)
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        m.addActions([self.a_save, self.a_save_as, self.a_save_copy])
        m.addSeparator()
        export = m.addMenu(tr("&Export"))
        export.addActions([self.a_export_png, self.a_export_svg])
        m.addSeparator()
        m.addActions([self.a_props, self.a_prefs])
        m.addSeparator()
        m.addAction(self.a_quit)

        m = mb.addMenu(tr("&Edit"))
        for group in ((self.a_undo, self.a_redo),
                      (self.a_cut, self.a_copy, self.a_paste, self.a_duplicate, self.a_delete),
                      (self.a_select_all, self.a_edit_topic),
                      (self.a_find, self.a_replace, self.a_find_next, self.a_find_prev)):
            m.addActions(list(group))
            m.addSeparator()

        m = mb.addMenu(tr("&View"))
        m.addActions([self.a_zoom_in, self.a_zoom_out, self.a_actual, self.a_fit, self.a_center])
        m.addSeparator()
        m.addActions([self.a_full_screen, self.a_zen])
        m.addSeparator()
        for action, text in ((self.props_dock.toggleViewAction(), tr("&Properties Panel")),
                             (self.markers_dock.toggleViewAction(), tr("&Markers Panel")),
                             (self.nav_dock.toggleViewAction(), tr("&Overview Panel")),
                             (self.toolbar.toggleViewAction(), tr("&Toolbar"))):
            action.setText(text)
            m.addAction(action)
        m.addAction(self.a_grid)

        m = mb.addMenu(tr("&Insert"))
        m.addActions([self.a_topic, self.a_topic_before, self.a_subtopic, self.a_parent])
        m.addSeparator()
        m.addAction(self.a_note)
        m.addMenu(self.markers.build_menu(self, tr("M&arker")))
        m.addAction(self.a_clear_markers)

        m = mb.addMenu(tr("&Map"))
        m.addMenu(self.structure_menu)
        m.addMenu(self.theme_menu)
        for group in ((self.a_fold, self.a_expand_all, self.a_collapse_all),
                      (self.a_move_up, self.a_move_down, self.a_sort_az, self.a_sort_za),
                      (self.a_new_sheet, self.a_rename_sheet, self.a_duplicate_sheet,
                       self.a_delete_sheet)):
            m.addSeparator()
            m.addActions(list(group))

        m = mb.addMenu(tr("&Help"))
        m.addActions([self.a_shortcuts, self.a_diagnostics])
        m.addSeparator()
        m.addAction(self.a_about)
        self._fill_recent()
        self._fill_theme_menu()

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.stats_label = QLabel()
        sb.addPermanentWidget(self.stats_label)
        for action in (self.a_zoom_out,):
            b = QToolButton()
            b.setDefaultAction(action)
            b.setAutoRaise(True)
            sb.addPermanentWidget(b)
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(10, 400)
        self.zoom_spin.setSingleStep(10)
        self.zoom_spin.setSuffix("%")
        self.zoom_spin.setKeyboardTracking(False)
        self.zoom_spin.setValue(100)
        self.zoom_spin.setToolTip(tr("Zoom"))
        self.zoom_spin.valueChanged.connect(lambda v: self.view.set_zoom(v / 100.0))
        sb.addPermanentWidget(self.zoom_spin)
        b = QToolButton()
        b.setDefaultAction(self.a_zoom_in)
        b.setAutoRaise(True)
        sb.addPermanentWidget(b)

    def _build_hint(self) -> None:
        self._hint = QLabel(self.view)
        self._hint.setStyleSheet("background: rgba(20, 20, 20, 205); color: white; "
                                 "padding: 8px 14px; border-radius: 8px;")
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._hint.hide()
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(2600)
        self._hint_timer.timeout.connect(self._hint.hide)

    def _connect_signals(self) -> None:
        v = self.view
        v.selection_changed.connect(self._update_ui)
        v.message.connect(self._show_message)
        v.escape_pressed.connect(self._on_escape)
        v.file_dropped.connect(self.open_path)
        v.context_menu_requested.connect(self._show_context_menu)
        v.zoom_changed.connect(self._on_zoom)
        v.note_requested.connect(lambda topic: QTimer.singleShot(0, lambda: self._edit_note(topic)))
        v.marker_clicked.connect(lambda topic, marker, pos: QTimer.singleShot(
            0, lambda: self.markers.show_popup(topic, marker, pos)))
        v.marker_dropped.connect(lambda topic, marker: self.markers.apply([topic], marker, "add"))
        self.marker_library.changed.connect(lambda: self.view.viewport().update())
        self.findbar.closed.connect(lambda: self.view.setFocus())

    def _apply_icons(self) -> None:
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        for action, name in self._icon_actions:
            action.setIcon(make_icon(name, color))

    def _apply_toolbar_style(self) -> None:
        self.toolbar.setToolButtonStyle(TOOLBAR_STYLE_MAP.get(
            self._pref("pref/toolbar_style", "text_under"),
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon))

    def _restore_window_state(self) -> None:
        restored = False
        try:
            geometry = self._pref("window/geometry")
            state = self._pref("window/state")
            if geometry:
                restored = self.restoreGeometry(QByteArray.fromHex(geometry.encode("ascii")))
            if state:
                self.restoreState(QByteArray.fromHex(state.encode("ascii")), STATE_VERSION)
        except (ValueError, UnicodeEncodeError):
            restored = False
        if not restored:
            self.resize(1280, 820)
            self.resizeDocks([self.nav_dock, self.props_dock], [220, 290], Qt.Orientation.Horizontal)

    def _save_window_state(self) -> None:
        self._store("window/geometry", self.saveGeometry().toHex().data().decode("ascii"))
        self._store("window/state", self.saveState(STATE_VERSION).toHex().data().decode("ascii"))

    # ================================================================ document
    def _set_document(self, document: Document) -> None:
        if self.document is not None:
            self.document.events.unsubscribe("changed", self._on_document_changed)
        self.document = document
        document.events.subscribe("changed", self._on_document_changed)
        self._sheet_index = 0
        self._doc_version += 1
        self.inspector.set_document(document)
        self.view.set_document(document, document.workbook.sheets[0])
        self._rebuild_tabs()
        self._update_ui()

    def _on_document_changed(self, command: Optional[Command] = None) -> None:
        self._doc_version += 1
        sheets = self.document.workbook.sheets
        target = getattr(command, "sheet", None)
        if target is not None and target in sheets and target is not self.view.sheet:
            self.view.set_sheet(target)          # show where an undo/redo happened
        elif self.view.sheet not in sheets:
            self.view.set_sheet(sheets[max(0, min(self._sheet_index, len(sheets) - 1))])
        else:
            self.view.refresh()
        self._rebuild_tabs()
        self._update_ui()

    def _commit_edits(self) -> None:
        if self.note_popup.isVisible():
            self.note_popup.close()          # saves the note being edited
        self.view.finish_edit(commit=True)
        self.inspector.commit_pending()

    def _exec(self, command: Command) -> bool:
        self._commit_edits()
        try:
            self.document.execute(command, self.view.sheet)
            return True
        except ValueError as exc:
            self._show_message(str(exc))
            return False

    def _set_sheet_attr(self, attr: str, value: str, label: str) -> None:
        sheet = self.view.sheet
        if sheet is not None and getattr(sheet, attr) != value:
            self._exec(SetSheetAttrCommand(sheet, attr, value, label=label))

    def _update_ui(self) -> None:
        doc, sheet = self.document, self.view.sheet
        if doc is None or sheet is None:
            return
        stack = doc.undo_stack
        self.a_undo.setEnabled(stack.can_undo)
        self.a_undo.setText(tr("&Undo {action}").format(action=stack.undo_label)
                            if stack.can_undo else tr("&Undo"))
        self.a_redo.setEnabled(stack.can_redo)
        self.a_redo.setText(tr("&Redo {action}").format(action=stack.redo_label)
                            if stack.can_redo else tr("&Redo"))
        topics = self.view.selected_topics()
        current = self.view.current_topic()
        non_root = any(t.parent is not None for t in topics)
        for a in (self.a_cut, self.a_delete, self.a_duplicate):
            a.setEnabled(non_root)
        self.a_copy.setEnabled(bool(topics))
        movable = current is not None and current.parent is not None
        self.a_parent.setEnabled(movable)
        self.a_topic_before.setEnabled(movable)
        self.a_move_up.setEnabled(movable and current.parent.index_of(current) > 0)
        self.a_move_down.setEnabled(movable and current.parent.children[-1] is not current)
        self.a_fold.setEnabled(any(t.children and t.parent is not None for t in topics))
        sort_target = current or sheet.root
        self.a_sort_az.setEnabled(len(sort_target.children) > 1)
        self.a_sort_za.setEnabled(len(sort_target.children) > 1)
        self.a_delete_sheet.setEnabled(len(doc.workbook.sheets) > 1)
        for a in self.structure_group.actions():
            a.setChecked(a.data() == sheet.structure)
        self.setWindowTitle(f"{doc.display_name}[*] \u2014 {APP_NAME}")
        self.setWindowModified(doc.is_modified)
        self.setWindowFilePath(str(doc.path) if doc.path else "")
        key = (id(sheet), self._doc_version)
        if self._count_cache[:2] != key:
            self._count_cache = (*key, sheet.count())
        text = tr("{n} topics").format(n=self._count_cache[2])
        if len(topics) > 1:
            text += " \u00b7 " + tr("{k} selected").format(k=len(topics))
        self.stats_label.setText(text)
        self.inspector.refresh()

    # ================================================================== sheets
    def _sheet_at(self, index: int) -> Optional[Sheet]:
        sheets = self.document.workbook.sheets
        return sheets[index] if 0 <= index < len(sheets) else None

    def _rebuild_tabs(self) -> None:
        sheets = self.document.workbook.sheets
        current = next((i for i, s in enumerate(sheets) if s is self.view.sheet), 0)
        self.tabs.blockSignals(True)
        try:
            while self.tabs.count() > len(sheets):
                self.tabs.removeTab(self.tabs.count() - 1)
            while self.tabs.count() < len(sheets):
                self.tabs.addTab("")
            for i, sheet in enumerate(sheets):
                text = sheet.title.replace("&", "&&")
                if self.tabs.tabText(i) != text:
                    self.tabs.setTabText(i, text)
                    self.tabs.setTabToolTip(i, sheet.title)
            self.tabs.setCurrentIndex(current)
        finally:
            self.tabs.blockSignals(False)
        self._sheet_index = current

    def _on_tab_changed(self, index: int) -> None:
        sheet = self._sheet_at(index)
        if sheet is None or sheet is self.view.sheet:
            return
        self._commit_edits()
        self.view.set_sheet(sheet)
        self._rebuild_tabs()
        self._update_ui()

    def _tab_menu(self, pos: QPoint) -> None:
        index = self.tabs.tabAt(pos)
        if index < 0:
            index = self._sheet_index
        menu = QMenu(self)
        entries = ((tr("New Sheet"), self._new_sheet, True),
                   (tr("Rename Sheet\u2026"), lambda: self._rename_sheet(index), True),
                   (tr("Duplicate Sheet"), lambda: self._duplicate_sheet(index), True),
                   (tr("Delete Sheet"), lambda: self._delete_sheet(index),
                    len(self.document.workbook.sheets) > 1))
        for text, fn, enabled in entries:
            a = menu.addAction(text)
            a.setEnabled(enabled)
            a.triggered.connect(lambda checked=False, f=fn: f())
        menu.exec(self.tabs.mapToGlobal(pos))

    def _new_sheet(self) -> None:
        wb = self.document.workbook
        sheet = self._apply_sheet_defaults(new_sheet(len(wb.sheets) + 1))
        self._exec(AddSheetCommand(wb, sheet, self._sheet_index + 1))

    def _rename_sheet(self, index: int) -> None:
        sheet = self._sheet_at(index)
        if sheet is None:
            return
        self._commit_edits()
        text, ok = QInputDialog.getText(self, tr("Rename Sheet"), tr("Sheet name:"),
                                        QLineEdit.EchoMode.Normal, sheet.title)
        text = text.strip()[:200]
        if ok and text and text != sheet.title:
            self._exec(SetSheetAttrCommand(sheet, "title", text, label=tr("Rename Sheet")))

    def _duplicate_sheet(self, index: int) -> None:
        src = self._sheet_at(index)
        if src is None:
            return
        self._commit_edits()
        root = clone_topic(src.root)
        root.type = ROOT
        copy_sheet = Sheet(title=tr("{title} (copy)").format(title=src.title), root=root,
                           theme_id=src.theme_id, structure=src.structure,
                           metadata=copy.deepcopy(src.metadata))
        self._exec(AddSheetCommand(self.document.workbook, copy_sheet, index + 1))

    def _delete_sheet(self, index: int) -> None:
        sheet = self._sheet_at(index)
        if sheet is not None and len(self.document.workbook.sheets) > 1:
            self._exec(RemoveSheetCommand(self.document.workbook, sheet))

    # ============================================================= edit / view
    def _text_focus(self):
        w = QApplication.focusWidget()
        return w if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit)) else None

    def _edit_cmd(self, name: Optional[str], fallback: Callable) -> None:
        widget = self._text_focus()
        if widget is not None:       # menu clicks act on the focused text field
            if name:
                getattr(widget, name)()
            return
        fallback()

    def _undo(self) -> None:
        widget = self._text_focus()
        if widget is not None:
            widget.undo()
            return
        self._commit_edits()
        self.document.undo()

    def _redo(self) -> None:
        widget = self._text_focus()
        if widget is not None:
            widget.redo()
            return
        self._commit_edits()
        self.document.redo()

    def _edit_current(self) -> None:
        topic = self.view.current_topic()
        if topic is not None:
            self.view.edit_topic(topic)

    def _edit_note(self, topic=None) -> None:
        """F4, Insert > Note and the note icon: XMind-style note editor next to the topic."""
        self._commit_edits()
        topic = topic if topic is not None else self.view.current_topic()
        if topic is None or not self.view.in_sheet(topic):
            self._show_message(tr("Select a topic to edit its note."))
            return
        if self.view.scene_.item_for(topic) is None:
            self.view.ops.reveal(topic)          # inside a collapsed branch
        self.view.select_topics([topic])
        self.view.ensure_visible(topic)
        if not self.note_popup.open_for(self.view, topic):
            self.props_dock.show()               # fallback: the Properties panel
            self.props_dock.raise_()
            self.inspector.focus_notes()

    def _commit_note_popup(self, topic, text: str) -> None:
        if self.view.in_sheet(topic) and text != topic.notes:
            self._exec(SetTopicAttrCommand(topic, "notes", text, label=tr("Edit Note")))

    def _go_root(self) -> None:
        if self.view.sheet is not None:
            self.view.select_topics([self.view.sheet.root])
            self.view.center_on_topic(self.view.sheet.root)

    def _set_grid(self, on: bool) -> None:
        self.view.set_grid(on)
        self._store("view/grid", "1" if on else "0")

    def _on_zoom(self, zoom: float) -> None:
        self.zoom_spin.blockSignals(True)
        self.zoom_spin.setValue(round(zoom * 100))
        self.zoom_spin.blockSignals(False)

    def _show_message(self, text: str) -> None:
        if self._zen:
            self._flash(text)
        else:
            self.statusBar().showMessage(text, 5000)

    def _flash(self, text: str) -> None:
        self._hint.setText(text)
        self._hint.adjustSize()
        self._hint.move(max(8, (self.view.width() - self._hint.width()) // 2), 16)
        self._hint.show()
        self._hint.raise_()
        self._hint_timer.start()

    def _on_escape(self) -> None:
        if self._zen:
            self.a_zen.setChecked(False)
        elif self.findbar.isVisible():
            self.findbar.close_bar()
        elif self.isFullScreen():
            self.a_full_screen.setChecked(False)

    def _set_full_screen(self, on: bool) -> None:
        if on and not self.isFullScreen():
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
        elif not on and self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()

    def _zen_widgets(self) -> dict[str, QWidget]:
        widgets = {"toolbar": self.toolbar, "props": self.props_dock, "nav": self.nav_dock,
                   "markers": self.markers_dock,
                   "status": self.statusBar(), "tabs": self.bottom_bar, "find": self.findbar}
        if not IS_MAC:
            widgets["menubar"] = self.menuBar()
        return widgets

    def _set_zen(self, on: bool) -> None:
        on = bool(on)
        if on == self._zen:
            return
        self._commit_edits()
        widgets = self._zen_widgets()
        if on:
            self._zen_state = {k: w.isVisible() for k, w in widgets.items()}
            self._zen_state["full"] = self.isFullScreen()
            self._was_maximized = self._was_maximized or self.isMaximized()
            for w in widgets.values():
                w.hide()
            self._zen = True
            if not self._zen_state["full"]:
                self.showFullScreen()
            self._flash(tr("Zen Mode \u2014 press Esc to exit"))
        else:
            self._zen = False
            for key, w in widgets.items():
                w.setVisible(self._zen_state.get(key, True))
            if not self._zen_state.get("full", False):
                self.showMaximized() if self._was_maximized else self.showNormal()
            self._hint.hide()
        self.view.setFocus()

    def _show_context_menu(self, pos: QPoint, topic) -> None:
        menu = QMenu(self)
        if topic is not None:
            for group in ((self.a_topic, self.a_topic_before, self.a_subtopic, self.a_parent),
                          (self.a_edit_topic, self.a_note),
                          (self.a_cut, self.a_copy, self.a_paste, self.a_duplicate, self.a_delete),
                          (self.a_fold, self.a_move_up, self.a_move_down, self.a_sort_az)):
                menu.addActions(list(group))
                menu.addSeparator()
            menu.addMenu(self.markers.build_menu(menu, tr("M&arkers")))
        else:
            menu.addActions([self.a_paste, self.a_select_all])
            menu.addSeparator()
            menu.addMenu(self.structure_menu)
            menu.addMenu(self.theme_menu)
            menu.addSeparator()
            menu.addActions([self.a_fit, self.a_actual, self.a_grid])
        menu.exec(pos)

    def _fill_theme_menu(self) -> None:
        menu = self.theme_menu
        menu.clear()
        if self._theme_group is not None:
            self._theme_group.deleteLater()
        self._theme_group = QActionGroup(self)
        current = self.view.sheet.theme_id if self.view.sheet is not None else ""
        for theme in self.ctx.themes.all():
            a = menu.addAction(theme.name.replace("&", "&&"))
            a.setCheckable(True)
            a.setChecked(theme.id == current)
            self._theme_group.addAction(a)
            a.triggered.connect(lambda checked=False, tid=theme.id: self._set_sheet_attr(
                "theme_id", tid, tr("Change Theme")))
        menu.addSeparator()
        menu.addActions([self.a_import_theme, self.a_export_theme])

    def _fill_recent(self) -> None:
        menu = self.recent_menu
        menu.clear()
        try:
            files = self.ctx.db.recent_files()
        except sqlite3.Error:
            files = []
        for i, f in enumerate(files):
            name = Path(f).name.replace("&", "&&")
            a = menu.addAction(f"&{i + 1} {name}" if i < 9 else name)
            a.setToolTip(f)
            a.triggered.connect(lambda checked=False, p=f: self.open_path(p))
        if not files:
            menu.addAction(tr("No Recent Files")).setEnabled(False)
        menu.addSeparator()
        clear = menu.addAction(tr("Clear Recent Files"))
        clear.setEnabled(bool(files))
        clear.triggered.connect(self._clear_recent)

    def _clear_recent(self) -> None:
        try:
            self.ctx.db.clear_recent()
        except sqlite3.Error as exc:
            log.warning("could not clear recent files: %s", exc)

    def _remember(self, path: Path) -> None:
        try:
            self.ctx.db.add_recent(path)
        except sqlite3.Error as exc:
            log.warning("could not update recent files: %s", exc)
        self._store("last_dir", str(path.parent))

    # ==================================================================== files
    def _background(self, label: str, fn: Callable):
        self._busy = True
        try:
            return run_in_background(self, label, fn)
        finally:
            self._busy = False

    def _maybe_save(self) -> bool:
        if self.document is None or not self.document.is_modified:
            return True
        std = QMessageBox.StandardButton
        answer = QMessageBox.warning(
            self, APP_NAME,
            tr("Do you want to save the changes to \u201c{name}\u201d?\n\n"
               "Your changes will be lost if you don't save them.").format(
                name=self.document.display_name),
            std.Save | std.Discard | std.Cancel, std.Save)
        if answer == std.Save:
            return self.save()
        return answer == std.Discard

    def new_document(self) -> None:
        if self._busy:
            return
        self._commit_edits()
        if not self._maybe_save():
            return
        self._lossy_source = None
        self._set_document(Document(self._new_workbook(), undo_limit=self._undo_limit()))

    def open_dialog(self) -> None:
        self._commit_edits()
        start = str(self.document.path.parent) if self.document.path else self._pref("last_dir")
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Open Workbook"), start,
            tr("VMap Workbook (*.vmap)") + ";;" + tr("All Files (*)"))
        if path:
            self.open_path(path)

    def open_path(self, path: str | Path) -> None:
        if self._busy:
            return
        path = Path(path)
        self._commit_edits()
        if (self.document.path is not None and _same_file(self.document.path, path)
                and not self.document.is_modified):
            self._show_message(tr("{name} is already open.").format(name=path.name))
            return
        if not self._maybe_save():
            return
        adapter = self.formats.get("vmap")
        try:
            result = self._background(tr("Opening {name}\u2026").format(name=path.name),
                                      lambda: adapter.import_file(path))
        except FileNotFoundError:
            QMessageBox.critical(self, tr("Open Workbook"),
                                 tr("The file \u201c{path}\u201d no longer exists.").format(path=path))
            try:
                self.ctx.db.remove_recent(path)
            except sqlite3.Error:
                pass
            return
        except (FormatError, OSError, ValueError) as exc:
            log.warning("open failed for %s: %s", path, exc)
            QMessageBox.critical(self, tr("Open Workbook"),
                                 tr("Could not open \u201c{name}\u201d:\n{error}").format(
                                     name=path.name, error=exc))
            return
        for theme in result.themes:       # embedded themes never replace installed ones
            existing = self.ctx.themes.get(theme.id)
            if existing is None:
                self.ctx.themes.register(theme)
            elif existing.to_dict() != theme.to_dict():
                result.report.warnings.append(tr(
                    "The embedded theme \u201c{id}\u201d differs from the installed theme with "
                    "the same id; the installed one is used.").format(id=theme.id))
        result.report.warnings.extend(
            self.marker_library.import_embedded(result.workbook.metadata.get(EMBED_KEY)))
        self._set_document(Document(result.workbook, path, undo_limit=self._undo_limit()))
        self._lossy_source = path if result.report.unsupported else None
        self._remember(path)
        self._show_message(tr("Opened {name}").format(name=path.name))
        if result.report.unsupported or result.report.warnings:
            show_report(self, tr("Open Report"), result.report)

    def _ask_save_path(self, title: str, default_name: str, file_filter: str,
                       suffix: str) -> Optional[Path]:
        start_dir = str(self.document.path.parent) if self.document.path else self._pref("last_dir")
        start = str(Path(start_dir) / default_name) if start_dir else default_name
        chosen, _ = QFileDialog.getSaveFileName(self, title, start, file_filter)
        if not chosen:
            return None
        path = Path(chosen)
        if path.suffix.lower() != suffix:
            path = path.with_name(path.name + suffix)
            if path.exists() and QMessageBox.question(
                    self, title, tr("\u201c{name}\u201d already exists. Replace it?").format(
                        name=path.name)) != YES:
                return None
        self._store("last_dir", str(path.parent))
        return path

    def _default_stem(self) -> str:
        if self.document.path is not None:
            return self.document.path.stem
        sheet = self.document.workbook.sheets[0]
        return _safe_name(self.document.workbook.title or sheet.root.title, tr("Untitled"))

    def _write(self, path: Path) -> bool:
        adapter, wb, themes = self.formats.get("vmap"), self.document.workbook, self.ctx.themes
        embed_custom_markers(wb, self.marker_library)   # custom images travel with the file
        try:
            report = self._background(tr("Saving {name}\u2026").format(name=path.name),
                                      lambda: adapter.export_file(wb, path, themes=themes))
        except (OSError, FormatError, ValueError) as exc:
            log.warning("save failed for %s: %s", path, exc)
            QMessageBox.critical(self, tr("Save Workbook"),
                                 tr("Could not save \u201c{name}\u201d:\n{error}").format(
                                     name=path.name, error=exc))
            return False
        if report.warnings:
            self._show_message(report.warnings[0])
        return True

    def _save_to(self, path: Path) -> bool:
        if self._lossy_source is not None and _same_file(path, self._lossy_source):
            std = QMessageBox.StandardButton
            if QMessageBox.warning(
                    self, tr("Overwrite Original File?"),
                    tr("This file contained content that this version cannot preserve (see the "
                       "open report). Saving over it will permanently remove that content."
                       "\n\nSave anyway?"), std.Save | std.Cancel, std.Cancel) != std.Save:
                return False
        if not self._write(path):
            return False
        if self._lossy_source is not None and _same_file(path, self._lossy_source):
            self._lossy_source = None
        self.document.mark_saved(path)
        self._remember(path)
        self._update_ui()
        self._show_message(tr("Saved {name}").format(name=path.name))
        return True

    def save(self) -> bool:
        if self._busy:
            return False
        self._commit_edits()
        if self.document.path is None:
            return self.save_as()
        return self._save_to(self.document.path)

    def save_as(self) -> bool:
        if self._busy:
            return False
        self._commit_edits()
        path = self._ask_save_path(tr("Save Workbook As"), f"{self._default_stem()}.vmap",
                                   tr("VMap Workbook (*.vmap)"), ".vmap")
        return self._save_to(path) if path is not None else False

    def save_copy(self) -> None:
        if self._busy:
            return
        self._commit_edits()
        path = self._ask_save_path(tr("Save a Copy"), f"{self._default_stem()} copy.vmap",
                                   tr("VMap Workbook (*.vmap)"), ".vmap")
        if path is not None and self._write(path):
            self._show_message(tr("Saved a copy to {name}").format(name=path.name))

    def export_image(self, kind: str) -> None:
        self._commit_edits()
        scale, transparent = 2.0, False
        if kind == "png":
            dialog = PngOptionsDialog(self)
            if not dialog.exec():
                return
            scale, transparent = dialog.values()
        sheet = self.view.sheet
        name = _safe_name(f"{self._default_stem()} - {sheet.title}", tr("Map"))
        file_filter = tr("PNG Image (*.png)") if kind == "png" else tr("SVG Image (*.svg)")
        path = self._ask_save_path(tr("Export Sheet"), f"{name}.{kind}", file_filter, f".{kind}")
        if path is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if kind == "png":
                size = export_png(self.view.scene_, path, scale, transparent)
            else:
                size = export_svg(self.view.scene_, path, title=sheet.title)
        except (OSError, ValueError) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr("Export Sheet"), str(exc))
            return
        QApplication.restoreOverrideCursor()
        self._show_message(tr("Exported {w}\u00d7{h} to {name}").format(
            w=size.width(), h=size.height(), name=path.name))

    # =================================================================== themes
    def import_theme(self) -> None:
        self._commit_edits()
        path, _ = QFileDialog.getOpenFileName(self, tr("Import Theme"), self._pref("last_dir"),
                                              tr("VMap Theme (*.json)"))
        if not path:
            return
        try:
            theme = read_theme_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Import Theme"),
                                tr("This file is not a valid theme:\n{error}").format(error=exc))
            return
        if theme.id in self.ctx.builtin_theme_ids:
            QMessageBox.warning(self, tr("Import Theme"), tr(
                "The theme id \u201c{id}\u201d is reserved by a built-in theme. Change the id in "
                "the file and try again.").format(id=theme.id))
            return
        if theme.id in self.ctx.themes and QMessageBox.question(
                self, tr("Import Theme"), tr("A theme with the id \u201c{id}\u201d is already "
                                             "installed. Replace it?").format(id=theme.id)) != YES:
            return
        try:
            self.ctx.install_theme(theme)
        except OSError as exc:
            self.ctx.themes.register(theme)
            self._show_message(tr("Theme loaded for this session only: {error}").format(error=exc))
        self.view.refresh()
        if QMessageBox.question(self, tr("Import Theme"), tr(
                "Theme \u201c{name}\u201d is installed. Apply it to the current sheet?").format(
                name=theme.name)) == YES:
            self._set_sheet_attr("theme_id", theme.id, tr("Change Theme"))
        self._update_ui()

    def export_theme(self) -> None:
        theme = self.ctx.themes.get_or_default(self.view.sheet.theme_id)
        path = self._ask_save_path(tr("Export Theme"), f"{theme.id}.json",
                                   tr("VMap Theme (*.json)"), ".json")
        if path is None:
            return
        try:
            path.write_text(json.dumps(theme.to_dict(), ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, tr("Export Theme"), str(exc))
            return
        self._show_message(tr("Theme exported to {name}").format(name=path.name))

    # ================================================================== dialogs
    def show_preferences(self) -> None:
        values = {"default_theme": self._pref("pref/default_theme", "classic"),
                  "default_structure": self._pref("pref/default_structure", DEFAULT_STRUCTURE),
                  "undo_limit": str(self._undo_limit()),
                  "toolbar_style": self._pref("pref/toolbar_style", "text_under")}
        dialog = PreferencesDialog(self, self.ctx.themes, values)
        if not dialog.exec():
            return
        for key, value in dialog.values().items():
            self._store(f"pref/{key}", value)
        self._apply_toolbar_style()
        self.document.undo_stack.limit = self._undo_limit()

    def show_properties(self) -> None:
        self._commit_edits()
        DocumentPropertiesDialog(self, self.document).exec()

    def show_diagnostics(self) -> None:
        TextReportDialog(self, tr("Diagnostics"), diagnostics_text(self.ctx, self.formats)).exec()

    def show_shortcuts(self) -> None:
        rows = [
            (tr("Insert subtopic"), f"{_native('Tab')} / {_native('Ins')}"),
            (tr("Insert topic after"), _native("Return")),
            (tr("Insert topic before"), _native("Shift+Return")),
            (tr("Insert parent topic"), _native("Ctrl+Return")),
            (tr("Edit topic text"), f"{_native('F2')} / {_native('Space')} / " + tr("start typing")),
            (tr("Finish editing / new line while editing"),
             f"{_native('Return')} / {_native('Shift+Return')}"),
            (tr("Cancel editing"), _native("Esc")),
            (tr("Delete topic"), f"{_native('Del')} / {_native('Backspace')}"),
            (tr("Select neighbouring topic"), tr("Arrow keys")),
            (tr("Extend selection"), tr("Shift + Arrow keys")),
            (tr("Move topic up / down"), f"{_native('Alt+Up')} / {_native('Alt+Down')}"),
            (tr("Fold / unfold branch"), _native("Ctrl+/")),
            (tr("Go to central topic"), _native("Home")),
            (tr("Zoom"), tr("Ctrl/\u2318 + mouse wheel, or pinch")),
            (tr("Pan"), tr("Drag empty canvas, or middle mouse button")),
            (tr("Box select"), tr("Shift/Ctrl + drag on empty canvas")),
            (tr("Re-parent / reorder topic"), tr("Drag a topic onto or beside another topic")),
        ]
        for a in self._all_actions:
            if not a.shortcut().isEmpty():
                keys = " / ".join(s.toString(NATIVE) for s in a.shortcuts())
                rows.append((str(a.property("vmap_label")), keys))
        ShortcutsDialog(self, rows).exec()

    # =================================================================== events
    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        kind = event.type()
        if kind == QEvent.Type.WindowStateChange and hasattr(self, "a_full_screen"):
            self.a_full_screen.blockSignals(True)
            self.a_full_screen.setChecked(self.isFullScreen())
            self.a_full_screen.blockSignals(False)
        elif (kind in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)
              and getattr(self, "_icon_actions", None)):
            self._apply_icons()

    def closeEvent(self, event) -> None:
        if self._busy:
            event.ignore()
            return
        self._commit_edits()
        if not self._maybe_save():
            event.ignore()
            return
        if self._zen:
            self.a_zen.setChecked(False)
        self._save_window_state()
        event.accept()
