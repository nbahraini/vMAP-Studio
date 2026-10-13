"""MapView: the interactive canvas.

Selection, keyboard navigation, in-place editing, drag-and-drop re-parenting,
zoom and pan. Canvas keys (Tab, Enter, Delete, Space, arrows) are handled here
rather than as window shortcuts so they never steal keys from text fields.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QEvent, QLineF, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTextCursor, QTransform
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsPathItem, QGraphicsView, QTextEdit

from vmap.core.commands import SetTopicAttrCommand
from vmap.core.document import Document
from vmap.core.model import Sheet, Topic
from vmap.i18n import tr
from vmap.themes.engine import ThemeRegistry
from vmap.ui.canvas.items import SELECTION_COLOR, TopicItem
from vmap.ui.canvas.operations import MapOperations
from vmap.ui.canvas.scene import MapScene

MIN_ZOOM = 0.1
MAX_ZOOM = 4.0
GRID_STEP = 24.0


def _kv(name: str) -> int:
    return getattr(Qt.Key, f"Key_{name}").value


(K_ESC, K_TAB, K_INSERT, K_RETURN, K_ENTER, K_DELETE, K_BACKSPACE, K_SPACE, K_F2,
 K_HOME, K_UP, K_DOWN, K_LEFT, K_RIGHT, K_SLASH) = (
    _kv(n) for n in ("Escape", "Tab", "Insert", "Return", "Enter", "Delete", "Backspace",
                     "Space", "F2", "Home", "Up", "Down", "Left", "Right", "Slash"))


def key_code(event) -> int:
    key = event.key()
    return key.value if hasattr(key, "value") else int(key)


@dataclass
class _DragState:
    item: TopicItem
    target: Optional[Topic] = None
    mode: str = ""


class TopicEditor(QTextEdit):
    """In-place editor. Enter commits, Shift+Enter = new line, Esc cancels, Tab commits + subtopic."""

    def __init__(self, view: "MapView", topic: Topic) -> None:
        super().__init__(view.viewport())
        self.view = view
        self.topic = topic
        self.min_height = 0
        self.setAcceptRichText(False)
        self.setTabChangesFocus(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        option = self.document().defaultTextOption()
        option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.document().setDefaultTextOption(option)
        self.document().setDocumentMargin(4)
        self.textChanged.connect(self.fit_height)

    def fit_height(self) -> None:
        height = math.ceil(self.document().size().height()) + 6
        self.resize(self.width(), max(self.min_height, height))

    def keyPressEvent(self, event) -> None:
        key = key_code(event)
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key in (K_RETURN, K_ENTER):
            if shift:
                self.insertPlainText("\n")
            else:
                self.view.finish_edit(commit=True)
            return
        if key == K_ESC:
            self.view.finish_edit(commit=False)
            return
        if key == K_TAB and not shift:
            self.view.finish_edit(commit=True)
            self.view.ops.add_subtopic()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if event.reason() not in (Qt.FocusReason.PopupFocusReason,
                                  Qt.FocusReason.ActiveWindowFocusReason):
            QTimer.singleShot(0, lambda: self.view.finish_edit(commit=True, editor=self))


class MapView(QGraphicsView):
    selection_changed = Signal()
    zoom_changed = Signal(float)
    viewport_changed = Signal()
    map_rendered = Signal()
    message = Signal(str)
    escape_pressed = Signal()
    file_dropped = Signal(str)
    context_menu_requested = Signal(QPoint, object)

    def __init__(self, themes: ThemeRegistry, parent=None) -> None:
        super().__init__(parent)
        self.scene_ = MapScene(themes, self)
        self.setScene(self.scene_)
        self.document: Optional[Document] = None
        self.sheet: Optional[Sheet] = None
        self.ops = MapOperations(self)
        self.show_grid = False
        self._zoom = 1.0
        self._current: Optional[Topic] = None
        self._editor: Optional[TopicEditor] = None
        self._suppress_selection = False
        self._pan_origin: Optional[QPointF] = None
        self._press: Optional[tuple[TopicItem, QPointF, bool]] = None
        self._drag: Optional[_DragState] = None
        self._drop_marker: Optional[QGraphicsPathItem] = None
        self._scene_rect = QRectF()
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.scene_.selectionChanged.connect(self._on_scene_selection)

    # ------------------------------------------------------------ document
    def set_document(self, document: Document, sheet: Sheet) -> None:
        self.finish_edit(commit=False)
        self._cancel_drag()
        self.document = document
        self.sheet = None
        self.set_sheet(sheet)

    def set_sheet(self, sheet: Sheet) -> None:
        self.finish_edit(commit=True)
        if sheet is self.sheet:
            self.refresh()
            return
        self._cancel_drag()
        self.sheet = sheet
        self._current = None
        self._scene_rect = QRectF()
        self.scene_.set_sheet(sheet)
        self.refresh()
        self.centerOn(QPointF(0.0, 0.0))
        self.viewport_changed.emit()

    def refresh(self) -> None:
        """Re-sync items with the model; keep a sensible selection."""
        if self.sheet is None:
            return
        self._suppress_selection = True
        try:
            self.scene_.sync()
            self._update_scene_rect()
            if not self.selected_items():
                fallback = self._visible_fallback(self._current)
                item = self.scene_.item_for(fallback)
                if item is not None:
                    item.setSelected(True)
                    self._current = fallback
        finally:
            self._suppress_selection = False
        self.selection_changed.emit()
        self.viewport_changed.emit()
        self.map_rendered.emit()

    def in_sheet(self, topic: Optional[Topic]) -> bool:
        if topic is None or self.sheet is None:
            return False
        node = topic
        while node.parent is not None:
            node = node.parent
        return node is self.sheet.root

    def _visible_fallback(self, topic: Optional[Topic]) -> Optional[Topic]:
        node = topic
        while node is not None:
            if self.scene_.item_for(node) is not None and self.in_sheet(node):
                return node
            node = node.parent
        return self.sheet.root if self.sheet else None

    def _update_scene_rect(self) -> None:
        content = self.scene_.content_rect()
        if content.isNull():
            return
        mx = max(600.0, self.viewport().width() / self._zoom)
        my = max(400.0, self.viewport().height() / self._zoom)
        rect = content.adjusted(-mx, -my, mx, my)
        if not self._scene_rect.isNull():
            rect = rect.united(self._scene_rect)   # only grow: no jumps while editing
        if rect != self._scene_rect:
            center = self.mapToScene(self.viewport().rect().center())
            self._scene_rect = rect
            self.setSceneRect(rect)
            self.centerOn(center)

    # ----------------------------------------------------------- selection
    def _on_scene_selection(self) -> None:
        if not self._suppress_selection:
            self.selection_changed.emit()

    def selected_items(self) -> list[TopicItem]:
        return [i for i in self.scene_.selectedItems() if isinstance(i, TopicItem)]

    def selected_topics(self) -> list[Topic]:
        """Selected topics in document (depth-first) order."""
        topics = [i.topic for i in self.selected_items()]
        if len(topics) < 2 or self.sheet is None:
            return topics
        order = {t.id: n for n, t in enumerate(self.sheet.topics())}
        return sorted(topics, key=lambda t: order.get(t.id, len(order)))

    def current_topic(self) -> Optional[Topic]:
        items = self.selected_items()
        if not items:
            return None
        item = self.scene_.item_for(self._current)
        if item is not None and item.isSelected():
            return self._current
        return items[0].topic

    def select_topics(self, topics: list[Topic], current: Optional[Topic] = None) -> None:
        self._suppress_selection = True
        try:
            self.scene_.clearSelection()
            for topic in topics:
                item = self.scene_.item_for(topic)
                if item is not None:
                    item.setSelected(True)
        finally:
            self._suppress_selection = False
        if current is not None:
            self._current = current
        elif topics:
            self._current = topics[-1]
        self.selection_changed.emit()

    def select_all(self) -> None:
        self.select_topics([i.topic for i in self.scene_.topic_items()], current=self._current)

    def ensure_visible(self, topic: Topic, margin: int = 60) -> None:
        item = self.scene_.item_for(topic)
        if item is not None:
            self.ensureVisible(item.mapRectToScene(item.box_rect()), margin, margin)

    def center_on_topic(self, topic: Topic) -> None:
        item = self.scene_.item_for(topic)
        if item is not None:
            self.centerOn(item)
            self.viewport_changed.emit()

    def center_on_root(self) -> None:
        self.centerOn(QPointF(0.0, 0.0))
        self.viewport_changed.emit()

    def navigate(self, key: int, extend: bool = False) -> None:
        current = self.current_topic()
        if current is None:
            if self.sheet is not None:
                self.select_topics([self.sheet.root])
            return
        origin_item = self.scene_.item_for(current)
        if origin_item is None:
            return
        dx, dy = {K_LEFT: (-1, 0), K_RIGHT: (1, 0), K_UP: (0, -1), K_DOWN: (0, 1)}[key]
        origin = origin_item.pos()
        best, best_score = None, math.inf
        for item in self.scene_.topic_items():
            if item is origin_item:
                continue
            v = item.pos() - origin
            primary = v.x() * dx + v.y() * dy
            if primary <= 1:
                continue
            score = primary + 2.5 * abs(v.x() * dy + v.y() * dx)
            if score < best_score:
                best, best_score = item, score
        if best is None:
            return
        if extend:
            self._current = best.topic
            best.setSelected(True)
        else:
            self.select_topics([best.topic])
        self.ensure_visible(best.topic, 50)

    # ------------------------------------------------------------- editing
    @property
    def is_editing(self) -> bool:
        return self._editor is not None

    def edit_topic(self, topic: Topic, initial_text: Optional[str] = None) -> None:
        self.finish_edit(commit=True)
        item = self.scene_.item_for(topic)
        if item is None or item.measured is None:
            return
        if not item.isSelected():
            self.select_topics([topic])
        self.ensure_visible(topic)
        style = item.style
        editor = TopicEditor(self, topic)
        font = QFont(item.measured.font)
        font.setPixelSize(max(6, round(item.measured.font.pixelSize() * self._zoom)))
        editor.setFont(font)
        fill = style["fill"] if style["fill"] != "none" else self.scene_.background_color.name()
        color = style["text_color"] if style["text_color"] != "none" else "#000000"
        editor.setStyleSheet(
            f"QTextEdit {{ background: {fill}; color: {color}; "
            f"border: 2px solid {SELECTION_COLOR.name()}; border-radius: 4px; }}")
        rect = self.mapFromScene(item.mapRectToScene(item.box_rect())).boundingRect()
        vp = self.viewport().rect()
        width = min(max(rect.width() + 24, 160), max(160, vp.width() - 8))
        x = max(4, min(rect.center().x() - width // 2, vp.width() - width - 4))
        editor.min_height = max(rect.height(), font.pixelSize() + 14)
        editor.setGeometry(int(x), int(rect.top()), int(width), int(editor.min_height))
        editor.setPlainText(topic.title if initial_text is None else initial_text)
        if initial_text is None:
            editor.selectAll()
        else:
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            editor.setTextCursor(cursor)
        self._editor = editor
        editor.fit_height()
        editor.show()
        editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def finish_edit(self, commit: bool = True, editor: Optional[TopicEditor] = None) -> None:
        current = self._editor
        if current is None or (editor is not None and editor is not current):
            return
        self._editor = None
        text = current.toPlainText().replace("\u2029", "\n").replace("\u2028", "\n").strip()
        topic = current.topic
        current.hide()
        current.deleteLater()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        if commit and text != topic.title and self.in_sheet(topic) and self.document is not None:
            self.document.execute(
                SetTopicAttrCommand(topic, "title", text, label=tr("Edit Topic Text")), self.sheet)

    # ---------------------------------------------------------------- zoom
    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, value: float, under_mouse: bool = False) -> None:
        value = max(MIN_ZOOM, min(MAX_ZOOM, float(value)))
        if math.isclose(value, self._zoom, rel_tol=1e-4):
            return
        self.finish_edit(commit=True)
        anchor = (QGraphicsView.ViewportAnchor.AnchorUnderMouse if under_mouse
                  else QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setTransformationAnchor(anchor)
        self.setTransform(QTransform.fromScale(value, value))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._zoom = value
        self._update_scene_rect()
        self.zoom_changed.emit(value)
        self.viewport_changed.emit()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.2)

    def actual_size(self) -> None:
        self.set_zoom(1.0)

    def fit_map(self) -> None:
        rect = self.scene_.content_rect()
        if rect.isNull():
            return
        self.finish_edit(commit=True)
        self.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.AspectRatioMode.KeepAspectRatio)
        z = max(MIN_ZOOM, min(1.5, self.transform().m11()))
        self.setTransform(QTransform.fromScale(z, z))
        self._zoom = z
        self._update_scene_rect()
        self.centerOn(rect.center())
        self.zoom_changed.emit(z)
        self.viewport_changed.emit()

    def set_grid(self, on: bool) -> None:
        self.show_grid = bool(on)
        self.resetCachedContent()
        self.viewport().update()

    # --------------------------------------------------------------- mouse
    def _topic_item_at(self, pos: QPoint) -> Optional[TopicItem]:
        for item in self.items(pos):
            if isinstance(item, TopicItem):
                return item
        return None

    def _begin_pan(self, pos: QPointF) -> None:
        self._pan_origin = QPointF(pos)
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mousePressEvent(self, event) -> None:
        self.finish_edit(commit=True)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        pos = event.position().toPoint()
        button = event.button()
        if button == Qt.MouseButton.MiddleButton:
            self._begin_pan(event.position())
            event.accept()
            return
        if button == Qt.MouseButton.RightButton:
            event.accept()  # the context menu event follows separately
            return
        if button != Qt.MouseButton.LeftButton or self.sheet is None:
            super().mousePressEvent(event)
            return
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        item = self._topic_item_at(pos)
        if item is None:
            if ctrl or shift:
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
                super().mousePressEvent(event)
                return
            self.scene_.clearSelection()
            self._begin_pan(event.position())
            event.accept()
            return
        if item.indicator_hit(self.mapToScene(pos)):
            self.ops.set_folded([item.topic], not item.topic.folded)
            event.accept()
            return
        if ctrl:
            if not item.isSelected():
                self._current = item.topic
            item.setSelected(not item.isSelected())
        elif shift:
            self._current = item.topic
            item.setSelected(True)
        else:
            was_multi = item.isSelected() and len(self.selected_items()) > 1
            self._current = item.topic
            if not item.isSelected():
                self.select_topics([item.topic])
            self._press = (item, QPointF(event.position()), was_multi)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._pan_origin is not None:
            delta = event.position() - self._pan_origin
            self._pan_origin = QPointF(event.position())
            hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
            hbar.setValue(hbar.value() - round(delta.x()))
            vbar.setValue(vbar.value() - round(delta.y()))
            event.accept()
            return
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            item, origin, _ = self._press
            if (self._drag is None and self.sheet is not None
                    and item.topic is not self.sheet.root
                    and (event.position() - origin).manhattanLength()
                    >= QApplication.startDragDistance()):
                self._begin_drag(item)
            if self._drag is not None:
                self._update_drag(event.position().toPoint())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        button = event.button()
        if self._pan_origin is not None and button in (Qt.MouseButton.LeftButton,
                                                       Qt.MouseButton.MiddleButton):
            self._pan_origin = None
            self.viewport().unsetCursor()
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton and self._drag is not None:
            self._finish_drag()
            self._press = None
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton and self._press is not None:
            item, _, was_multi = self._press
            self._press = None
            if was_multi and item.scene() is self.scene_:
                self.select_topics([item.topic])
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self.dragMode() != QGraphicsView.DragMode.NoDrag:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            items = self.selected_items()
            if items:
                self._current = items[-1].topic
            self.selection_changed.emit()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            item = self._topic_item_at(pos)
            if item is not None and not item.indicator_hit(self.mapToScene(pos)):
                self.edit_topic(item.topic)
        event.accept()  # double-click on blank canvas: floating topics arrive in Phase 2

    def contextMenuEvent(self, event) -> None:
        self.finish_edit(commit=True)
        item = self._topic_item_at(event.pos())
        if item is not None and not item.isSelected():
            self.select_topics([item.topic])
        self.context_menu_requested.emit(event.globalPos(), item.topic if item else None)
        event.accept()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.set_zoom(self._zoom * math.pow(1.0015, delta), under_mouse=True)
            event.accept()
            return
        super().wheelEvent(event)

    def viewportEvent(self, event) -> bool:
        if (event.type() == QEvent.Type.NativeGesture
                and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture):
            self.set_zoom(self._zoom * (1.0 + event.value()), under_mouse=True)
            return True
        return super().viewportEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.viewport_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.viewport_changed.emit()

    # --------------------------------------------------------- drag & drop
    def _begin_drag(self, item: TopicItem) -> None:
        self._drag = _DragState(item)
        item.setOpacity(0.35)
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._drop_marker is None or self._drop_marker.scene() is not self.scene_:
            marker = QGraphicsPathItem()
            pen = QPen(SELECTION_COLOR, 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            marker.setPen(pen)
            marker.setZValue(10.0)
            self.scene_.addItem(marker)
            self._drop_marker = marker
        self._drop_marker.hide()

    def _autoscroll(self, pos: QPoint) -> None:
        margin, step = 28, 18
        vp = self.viewport().rect()
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        if pos.x() < margin:
            hbar.setValue(hbar.value() - step)
        elif pos.x() > vp.width() - margin:
            hbar.setValue(hbar.value() + step)
        if pos.y() < margin:
            vbar.setValue(vbar.value() - step)
        elif pos.y() > vp.height() - margin:
            vbar.setValue(vbar.value() + step)

    def _update_drag(self, pos: QPoint) -> None:
        drag = self._drag
        if drag is None or self.sheet is None or self._drop_marker is None:
            return
        self._autoscroll(pos)
        dragged = drag.item.topic
        target: Optional[TopicItem] = None
        for item in self.items(pos):
            if (isinstance(item, TopicItem) and item is not drag.item
                    and not dragged.is_ancestor_of(item.topic)):
                target = item
                break
        if target is None:
            drag.target = None
            self._drop_marker.hide()
            return
        box = target.mapRectToScene(target.box_rect())
        rel = (self.mapToScene(pos).y() - box.top()) / max(1.0, box.height())
        is_root = target.topic is self.sheet.root
        if not is_root and rel < 0.25:
            mode = "before"
        elif not is_root and rel > 0.75:
            mode = "after"
        else:
            mode = "child"
        path = QPainterPath()
        if mode == "child":
            path.addRoundedRect(box.adjusted(-6, -6, 6, 6), 6, 6)
        else:
            y = box.top() - 5 if mode == "before" else box.bottom() + 5
            path.moveTo(box.left(), y)
            path.lineTo(box.right(), y)
        self._drop_marker.setPath(path)
        self._drop_marker.show()
        drag.target, drag.mode = target.topic, mode

    def _finish_drag(self) -> None:
        drag = self._drag
        self._drag = None
        if drag is None:
            return
        drag.item.setOpacity(1.0)
        if self._drop_marker is not None:
            self._drop_marker.hide()
        self.viewport().unsetCursor()
        if drag.target is not None:
            self.ops.drop_topic(drag.item.topic, drag.target, drag.mode)

    def _cancel_drag(self) -> None:
        if self._drag is not None:
            self._drag.item.setOpacity(1.0)
            self._drag = None
        if self._drop_marker is not None:
            self._drop_marker.hide()
        self._press = None
        self._pan_origin = None
        self.viewport().unsetCursor()

    # ------------------------------------------------- dropping .vmap files
    @staticmethod
    def _vmap_path(mime) -> Optional[str]:
        if mime is not None and mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".vmap"):
                    return url.toLocalFile()
        return None

    def dragEnterEvent(self, event) -> None:
        if self._vmap_path(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._vmap_path(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        path = self._vmap_path(event.mimeData())
        if path:
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.file_dropped.emit(path))
        else:
            super().dropEvent(event)

    # ------------------------------------------------------------ keyboard
    def focusNextPrevChild(self, next_child: bool) -> bool:
        return False  # Tab inserts a subtopic on the canvas

    def keyPressEvent(self, event) -> None:
        if self.sheet is None or self.document is None:
            super().keyPressEvent(event)
            return
        key = key_code(event)
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        meta = bool(mods & Qt.KeyboardModifier.MetaModifier)
        if key == K_ESC:
            if self._drag is not None or self._pan_origin is not None:
                self._cancel_drag()
            else:
                self.escape_pressed.emit()
            return
        if key in (K_TAB, K_INSERT) and not (ctrl or alt or shift):
            self.ops.add_subtopic()
            return
        if key in (K_RETURN, K_ENTER) and not alt:
            if ctrl:
                self.ops.add_parent()
            elif shift:
                self.ops.add_sibling(before=True)
            else:
                self.ops.add_sibling()
            return
        if key in (K_DELETE, K_BACKSPACE) and not (ctrl or alt):
            self.ops.delete_selected()
            return
        if key in (K_SPACE, K_F2) and not (ctrl or alt or meta):
            topic = self.current_topic()
            if topic is not None:
                self.edit_topic(topic)
            return
        if key == K_HOME and not (ctrl or alt):
            self.select_topics([self.sheet.root])
            self.center_on_topic(self.sheet.root)
            return
        if alt and key in (K_UP, K_DOWN):
            self.ops.move_sibling(-1 if key == K_UP else 1)
            return
        if key in (K_LEFT, K_RIGHT, K_UP, K_DOWN) and not (ctrl or alt):
            self.navigate(key, extend=shift)
            return
        if ctrl and key == K_SLASH:
            self.ops.toggle_fold()
            return
        text = event.text()
        if text and text.isprintable() and not (ctrl and not alt) and not meta:
            topic = self.current_topic()
            if topic is not None:
                self.edit_topic(topic, initial_text=text)
                return
        super().keyPressEvent(event)

    def inputMethodEvent(self, event) -> None:
        text = event.commitString()
        topic = self.current_topic()
        if text and topic is not None and not self.is_editing:
            self.edit_topic(topic, initial_text=text)
            event.accept()
            return
        super().inputMethodEvent(event)

    # ---------------------------------------------------------- background
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        if not self.show_grid or self._zoom < 0.3:
            return
        bg = self.scene_.background_color
        color = QColor(0, 0, 0, 24) if bg.lightness() > 128 else QColor(255, 255, 255, 28)
        painter.setPen(QPen(color, 0))  # width 0 = cosmetic hairline
        left = math.floor(rect.left() / GRID_STEP) * GRID_STEP
        top = math.floor(rect.top() / GRID_STEP) * GRID_STEP
        lines: list[QLineF] = []
        x = left
        while x < rect.right():
            lines.append(QLineF(x, rect.top(), x, rect.bottom()))
            x += GRID_STEP
        y = top
        while y < rect.bottom():
            lines.append(QLineF(rect.left(), y, rect.right(), y))
            y += GRID_STEP
        painter.drawLines(lines)
