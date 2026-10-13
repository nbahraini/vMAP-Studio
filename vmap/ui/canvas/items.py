"""Graphics items (topics, branch connectors) and text measurement.

Text is wrapped once at measure time and painted line by line, so wrapping
never changes with zoom level. Font sizes are style points converted to
pixels, which keeps screen, PNG and SVG output identical.
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem

from vmap.core.markers import display_markers
from vmap.core.model import Topic
from vmap.mindmap.layouts import NodeBox
from vmap.ui.markers import MARKER_GAP, MARKER_SIZE, paint_marker

PT_TO_PX = 96.0 / 72.0
MAX_TITLE_CHARS = 2000
NOTE_ICON_SIZE = 14.0
NOTE_GAP = 5.0
NOTE_ICON_W = NOTE_GAP + NOTE_ICON_SIZE
INDICATOR_R = 7.0
INDICATOR_GAP = 10.0
SELECT_MARGIN = 4.0
SELECTION_COLOR = QColor("#2E7CF6")


def style_font(style: dict[str, Any]) -> QFont:
    font = QFont(style["font_family"]) if style.get("font_family") else QFont()
    font.setPixelSize(max(1, round(float(style["font_size"]) * PT_TO_PX)))
    font.setBold(bool(style.get("bold")))
    font.setItalic(bool(style.get("italic")))
    return font


def is_rtl(text: str) -> bool:
    """Direction of the first strong character (Persian/Arabic/Hebrew -> True)."""
    for ch in text:
        kind = unicodedata.bidirectional(ch)
        if kind in ("R", "AL"):
            return True
        if kind == "L":
            return False
    return False


@dataclass(frozen=True, eq=False)
class TextBlock:
    lines: tuple[tuple[str, float, bool], ...]   # (text, width, rtl)
    width: float
    height: float
    line_height: float
    ascent: float


def _break_word(word: str, fm: QFontMetricsF, max_width: float) -> list[str]:
    parts: list[str] = []
    while len(word) > 1 and fm.horizontalAdvance(word) > max_width:
        lo, hi = 1, len(word) - 1
        while lo < hi:  # largest prefix that fits (binary search)
            mid = (lo + hi + 1) // 2
            if fm.horizontalAdvance(word[:mid]) <= max_width:
                lo = mid
            else:
                hi = mid - 1
        parts.append(word[:lo])
        word = word[lo:]
    parts.append(word)
    return parts


def wrap_text(text: str, fm: QFontMetricsF, max_width: float) -> TextBlock:
    lines: list[str] = []
    for para in text.split("\n"):
        current = ""
        for word in para.split(" "):
            candidate = f"{current} {word}" if current else word
            if fm.horizontalAdvance(candidate) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            pieces = _break_word(word, fm, max_width)
            lines.extend(pieces[:-1])
            current = pieces[-1]
        lines.append(current)
    measured = tuple((ln, fm.horizontalAdvance(ln), is_rtl(ln)) for ln in lines)
    width = max((w for _, w, _ in measured), default=0.0)
    height = fm.height() + (len(lines) - 1) * fm.lineSpacing()
    return TextBlock(measured, width, height, fm.lineSpacing(), fm.ascent())


@dataclass(frozen=True, eq=False)
class Measured:
    font: QFont
    block: TextBlock
    text_width: float
    width: float
    height: float
    note_icon: bool
    markers_w: float = 0.0


def measure_topic(title: str, has_notes: bool, style: dict[str, Any],
                  markers: int = 0) -> Measured:
    font = style_font(style)
    fm = QFontMetricsF(font)
    pad_x, pad_y = float(style["padding_x"]), float(style["padding_y"])
    icon = NOTE_ICON_W if has_notes else 0.0
    markers_w = markers * (MARKER_SIZE + MARKER_GAP)
    max_text = max(24.0, float(style["max_width"]) - 2 * pad_x - icon - markers_w)
    text = title if len(title) <= MAX_TITLE_CHARS else title[:MAX_TITLE_CHARS] + "\u2026"
    block = wrap_text(text, fm, max_text)
    text_w = max(block.width, fm.averageCharWidth() * 3)
    content_w = text_w + icon + markers_w
    content_h = max(block.height, MARKER_SIZE if markers else 0.0,
                    NOTE_ICON_SIZE if has_notes else 0.0)
    shape = style.get("shape")
    if shape == "ellipse":
        content_w, content_h = content_w * 1.42, content_h * 1.42
    w = content_w + 2 * pad_x
    h = content_h + 2 * pad_y
    if shape == "pill":
        w += h * 0.3
    return Measured(font, block, text_w, float(math.ceil(w)), float(math.ceil(h)), bool(icon),
                    markers_w)


def out_anchor(box: NodeBox, side: int, shape: str, is_root: bool) -> QPointF:
    x = box.right if side > 0 else box.left
    if shape == "underline" and not is_root:
        return QPointF(x, box.bottom)
    return QPointF(x, box.cy)


def in_anchor(box: NodeBox, shape: str) -> QPointF:
    x = box.left if box.side > 0 else box.right
    if shape == "underline":
        return QPointF(x, box.bottom)
    return QPointF(x, box.cy)


def connector_path(start: QPointF, end: QPointF, line_style: str) -> QPainterPath:
    path = QPainterPath(start)
    if line_style == "straight":
        path.lineTo(end)
    elif line_style == "elbow":
        mid = start.x() + (end.x() - start.x()) / 2
        path.lineTo(QPointF(mid, start.y()))
        path.lineTo(QPointF(mid, end.y()))
        path.lineTo(end)
    else:
        dx = (end.x() - start.x()) * 0.5
        path.cubicTo(QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y()), end)
    return path


class TopicItem(QGraphicsItem):
    """One topic box. Positioned at its centre; geometry comes from the layout."""

    def __init__(self, topic: Topic) -> None:
        super().__init__()
        self.topic = topic
        self.style: dict[str, Any] = {}
        self.measured: Optional[Measured] = None
        self.w = self.h = 0.0
        self.side = 0
        self.has_children = False
        self.folded = False
        self.hovered = False
        self._geometry: tuple = ()
        self._bounds = QRectF()
        self._markers: tuple[str, ...] = ()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(1.0)

    def apply(self, topic: Topic, style: dict[str, Any], measured: Measured,
              box: NodeBox, has_children: bool) -> None:
        markers = tuple(display_markers(topic.markers))
        changed = (topic is not self.topic or style != self.style or markers != self._markers
                   or measured is not self.measured or topic.folded != self.folded)
        self.topic, self.style, self.measured, self.folded = topic, style, measured, topic.folded
        self._markers = markers
        geometry = (measured.width, measured.height, box.side, has_children, style["shape"])
        if geometry != self._geometry:
            self.prepareGeometryChange()
            self._geometry = geometry
            self.w, self.h = measured.width, measured.height
            self.side, self.has_children = box.side, has_children
            self._bounds = self._compute_bounds()
            changed = True
        pos = QPointF(box.cx, box.cy)
        if self.pos() != pos:
            self.setPos(pos)
        if changed:   # notes show in a balloon over the note icon instead of a tooltip
            self.update()

    def box_rect(self) -> QRectF:
        return QRectF(-self.w / 2, -self.h / 2, self.w, self.h)

    def indicator_center(self) -> QPointF:
        y = self.h / 2 if self.style.get("shape") == "underline" else 0.0
        x = self.w / 2 + INDICATOR_GAP if self.side > 0 else -self.w / 2 - INDICATOR_GAP
        return QPointF(x, y)

    def _has_indicator(self) -> bool:
        return self.has_children and self.side != 0

    def _compute_bounds(self) -> QRectF:
        m = SELECT_MARGIN + 2
        rect = self.box_rect().adjusted(-m, -m, m, m)
        if self._has_indicator():
            c, r = self.indicator_center(), INDICATOR_R + 2
            rect = rect.united(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
        return rect

    def boundingRect(self) -> QRectF:
        return self._bounds

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        path.addRect(self.box_rect().adjusted(-2, -2, 2, 2))
        if self._has_indicator():
            path.addEllipse(self.indicator_center(), INDICATOR_R + 2, INDICATOR_R + 2)
        return path

    def indicator_hit(self, scene_pos: QPointF) -> bool:
        if not self._has_indicator():
            return False
        d = self.mapFromScene(scene_pos) - self.indicator_center()
        return math.hypot(d.x(), d.y()) <= INDICATOR_R + 2

    # ----------------------------------------------- markers and note icon
    def _content_left(self) -> float:
        m = self.measured
        if m is None:
            return 0.0
        return -(m.markers_w + m.text_width + (NOTE_ICON_W if m.note_icon else 0.0)) / 2

    def marker_rects(self) -> list[tuple[str, QRectF]]:
        """Marker icons left of the title, in item coordinates and display order."""
        if self.measured is None:
            return []
        x, rects = self._content_left(), []
        for marker_id in self._markers:
            rects.append((marker_id, QRectF(x, -MARKER_SIZE / 2, MARKER_SIZE, MARKER_SIZE)))
            x += MARKER_SIZE + MARKER_GAP
        return rects

    def note_icon_rect(self) -> Optional[QRectF]:
        m = self.measured
        if m is None or not m.note_icon:
            return None
        x = self._content_left() + m.markers_w + m.text_width + NOTE_GAP
        return QRectF(x, -NOTE_ICON_SIZE / 2, NOTE_ICON_SIZE, NOTE_ICON_SIZE)

    def marker_at(self, scene_pos: QPointF) -> Optional[str]:
        p = self.mapFromScene(scene_pos)
        for marker_id, rect in self.marker_rects():
            if rect.adjusted(-1, -1, 1, 1).contains(p):
                return marker_id
        return None

    def note_icon_hit(self, scene_pos: QPointF) -> bool:
        rect = self.note_icon_rect()
        return rect is not None and rect.adjusted(-3, -3, 3, 3).contains(self.mapFromScene(scene_pos))

    def hoverEnterEvent(self, event) -> None:
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        m = self.measured
        if m is None:
            return
        s = self.style
        scene = self.scene()
        exporting = bool(getattr(scene, "export_mode", False))
        background = getattr(scene, "background_color", QColor("#FFFFFF"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rect = self.box_rect()
        shape = s["shape"]
        bw = float(s["border_width"])
        fill = None if s["fill"] == "none" else QColor(s["fill"])
        border = None if (s["border"] == "none" or bw <= 0) else QColor(s["border"])
        if shape == "underline":
            if fill is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawRoundedRect(rect, 3, 3)
            if border is not None:
                painter.setPen(QPen(border, bw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                y = rect.bottom() - bw / 2
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        else:
            painter.setPen(QPen(border, bw) if border is not None else Qt.PenStyle.NoPen)
            painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
            r = rect.adjusted(bw / 2, bw / 2, -bw / 2, -bw / 2) if border is not None else rect
            if shape == "rect":
                painter.drawRect(r)
            elif shape == "ellipse":
                painter.drawEllipse(r)
            else:
                radius = r.height() / 2 if shape == "pill" else min(6.0, r.height() / 3)
                painter.drawRoundedRect(r, radius, radius)

        block = m.block
        text_color = QColor(0, 0, 0, 0) if s["text_color"] == "none" else QColor(s["text_color"])
        painter.setFont(m.font)
        painter.setPen(text_color)
        library = getattr(scene, "marker_library", None)
        for marker_id, marker_rect in self.marker_rects():
            paint_marker(painter, marker_rect, marker_id, library)
        left = self._content_left() + m.markers_w
        y = -block.height / 2 + block.ascent
        for text, width, rtl in block.lines:
            painter.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl
                                       else Qt.LayoutDirection.LeftToRight)
            painter.drawText(QPointF(left + (m.text_width - width) / 2, y), text)
            y += block.line_height
        painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        note_rect = self.note_icon_rect()
        if note_rect is not None:
            self._paint_note_icon(painter, note_rect)

        if self._has_indicator():
            if self.folded:
                self._paint_indicator(painter, True, background)
            elif (self.hovered or self.isSelected()) and not exporting:
                self._paint_indicator(painter, False, background)

        if exporting:
            return
        if self.isSelected():
            painter.setPen(QPen(SELECTION_COLOR, 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            m2 = SELECT_MARGIN
            painter.drawRoundedRect(rect.adjusted(-m2, -m2, m2, m2), 5, 5)
        elif self.hovered:
            color = QColor(SELECTION_COLOR)
            color.setAlpha(110)
            painter.setPen(QPen(color, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 5, 5)

    @staticmethod
    def _paint_note_icon(painter: QPainter, r: QRectF) -> None:
        """Yellow note sheet with a folded corner (original artwork)."""
        painter.save()
        painter.translate(r.topLeft())
        painter.scale(r.width() / 16.0, r.height() / 16.0)
        page = QPainterPath(QPointF(2.6, 1.2))
        for x, y in ((10.4, 1.2), (13.6, 4.4), (13.6, 14.8), (2.6, 14.8)):
            page.lineTo(x, y)
        page.closeSubpath()
        painter.setPen(QPen(QColor("#B8860B"), 0.9))
        painter.setBrush(QColor("#FFF3A6"))
        painter.drawPath(page)
        fold = QPainterPath(QPointF(10.4, 1.2))
        fold.lineTo(10.4, 4.4)
        fold.lineTo(13.6, 4.4)
        fold.closeSubpath()
        painter.setBrush(QColor("#F2D35B"))
        painter.drawPath(fold)
        painter.setPen(QPen(QColor("#8D6E00"), 0.9))
        for y in (7.0, 9.4, 11.8):
            painter.drawLine(QPointF(4.6, y), QPointF(11.6, y))
        painter.restore()

    def _paint_indicator(self, painter: QPainter, folded: bool, background: QColor) -> None:
        c = self.indicator_center()
        line = self.style.get("line_color", "#7A8899")
        color = QColor("#7A8899") if line == "none" else QColor(line)
        painter.setPen(QPen(color, 1.3))
        painter.setBrush(background)
        painter.drawEllipse(c, INDICATOR_R, INDICATOR_R)
        painter.drawLine(QPointF(c.x() - 3.5, c.y()), QPointF(c.x() + 3.5, c.y()))
        if folded:
            painter.drawLine(QPointF(c.x(), c.y() - 3.5), QPointF(c.x(), c.y() + 3.5))


class ConnectorItem(QGraphicsPathItem):
    """Branch line from a parent topic to one child."""

    def __init__(self) -> None:
        super().__init__()
        self._key: tuple = ()
        self.setZValue(0.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)

    def set_route(self, start: QPointF, end: QPointF, line_style: str,
                  color: str, width: float) -> None:
        key = (round(start.x(), 2), round(start.y(), 2), round(end.x(), 2), round(end.y(), 2),
               line_style, color, width)
        if key == self._key:
            return
        self._key = key
        if color == "none" or width <= 0:
            self.setVisible(False)
            return
        self.setVisible(True)
        self.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                         Qt.PenJoinStyle.RoundJoin))
        self.setPath(connector_path(start, end, line_style))
