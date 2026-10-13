"""MapScene: turns a Sheet into graphics items using the layout and theme engines.

sync() is incremental: items are cached by topic id and only touched when
their geometry or style actually changed; text measurement is memoised.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsScene

from vmap.core.model import Sheet, Topic
from vmap.mindmap.layouts import compute_layout, visible_children
from vmap.themes.engine import Theme, ThemeRegistry, resolve_style
from vmap.ui.canvas.items import (INDICATOR_GAP, INDICATOR_R, ConnectorItem, Measured,
                                  TopicItem, in_anchor, measure_topic, out_anchor)

MEASURE_CACHE_LIMIT = 20_000


class MapScene(QGraphicsScene):
    def __init__(self, themes: ThemeRegistry, parent=None) -> None:
        super().__init__(parent)
        self.themes = themes
        self.sheet: Optional[Sheet] = None
        self.theme: Optional[Theme] = None
        self.export_mode = False
        self.background_color = QColor("#FFFFFF")
        self.setBackgroundBrush(self.background_color)
        self.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.BspTreeIndex)
        self._items: dict[str, TopicItem] = {}
        self._connectors: dict[str, ConnectorItem] = {}
        self._styles: dict[str, dict] = {}
        self._measure_cache: dict[tuple, Measured] = {}
        self._content = QRectF()

    # ---------------------------------------------------------------- state
    def set_sheet(self, sheet: Optional[Sheet]) -> None:
        if sheet is not self.sheet:
            self.clear_items()
            self.sheet = sheet

    def clear_items(self) -> None:
        for item in list(self._items.values()) + list(self._connectors.values()):
            self.removeItem(item)
        self._items.clear()
        self._connectors.clear()
        self._styles.clear()
        self._content = QRectF()

    def item_for(self, topic: Optional[Topic]) -> Optional[TopicItem]:
        if topic is None:
            return None
        item = self._items.get(topic.id)
        return item if item is not None and item.topic is topic else None

    def style_for(self, topic: Topic) -> Optional[dict]:
        return self._styles.get(topic.id)

    def topic_items(self) -> list[TopicItem]:
        return list(self._items.values())

    def content_rect(self) -> QRectF:
        return QRectF(self._content)

    @contextmanager
    def exporting(self, transparent: bool = False) -> Iterator[None]:
        old_brush = self.backgroundBrush()
        self.export_mode = True
        if transparent:
            self.setBackgroundBrush(Qt.BrushStyle.NoBrush)
        try:
            yield
        finally:
            self.export_mode = False
            if transparent:
                self.setBackgroundBrush(old_brush)

    def _measure(self, topic: Topic, style: dict) -> Measured:
        key = (topic.title, bool(topic.notes), style["font_family"], style["font_size"],
               style["bold"], style["italic"], style["max_width"], style["padding_x"],
               style["padding_y"], style["shape"])
        m = self._measure_cache.get(key)
        if m is None:
            if len(self._measure_cache) >= MEASURE_CACHE_LIMIT:
                self._measure_cache.clear()
            m = self._measure_cache[key] = measure_topic(topic.title, bool(topic.notes), style)
        return m

    # ----------------------------------------------------------------- sync
    def sync(self) -> None:
        sheet = self.sheet
        if sheet is None:
            return
        theme = self.themes.get_or_default(sheet.theme_id)
        self.theme = theme
        bg = QColor(theme.background)
        if bg != self.background_color:
            self.background_color = bg
            self.setBackgroundBrush(bg)

        info: dict[str, tuple[Topic, dict, Measured]] = {}
        stack: list[tuple[Topic, int, int]] = [(sheet.root, 0, -1)]
        while stack:
            topic, depth, branch = stack.pop()
            level = "root" if depth == 0 else ("main" if depth == 1 else "sub")
            color = theme.branch_color(branch) if branch >= 0 else None
            style = resolve_style(theme, topic, level, color)
            info[topic.id] = (topic, style, self._measure(topic, style))
            kids = topic.children if depth == 0 else visible_children(topic)
            for index, child in enumerate(kids):
                stack.append((child, depth + 1, index if depth == 0 else branch))

        boxes = compute_layout(
            sheet.root, lambda t: (info[t.id][2].width, info[t.id][2].height),
            sheet.structure, theme.h_gap, theme.v_gap, theme.root_gap)

        pad = INDICATOR_GAP + INDICATOR_R + 4
        content = QRectF()
        for tid, box in boxes.items():
            topic, style, measured = info[tid]
            item = self._items.get(tid)
            if item is None:
                item = TopicItem(topic)
                self.addItem(item)
                self._items[tid] = item
            item.apply(topic, style, measured, box, bool(topic.children))
            content = content.united(QRectF(box.left - pad, box.top - pad,
                                            box.w + 2 * pad, box.h + 2 * pad))
        for tid in [k for k in self._items if k not in boxes]:
            self.removeItem(self._items.pop(tid))

        root_id = sheet.root.id
        for tid, box in boxes.items():
            topic, style, _ = info[tid]
            parent = topic.parent
            if tid == root_id or parent is None or parent.id not in boxes:
                continue
            parent_style = info[parent.id][1]
            start = out_anchor(boxes[parent.id], box.side, parent_style["shape"],
                               parent is sheet.root)
            end = in_anchor(box, style["shape"])
            conn = self._connectors.get(tid)
            if conn is None:
                conn = ConnectorItem()
                self.addItem(conn)
                self._connectors[tid] = conn
            conn.set_route(start, end, theme.line_style, style["line_color"],
                           float(style["line_width"]))
        for tid in [k for k in self._connectors if k not in boxes or k == root_id]:
            self.removeItem(self._connectors.pop(tid))

        self._styles = {tid: info[tid][1] for tid in boxes}
        self._content = content
