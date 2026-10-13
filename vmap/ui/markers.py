"""Marker artwork, custom PNG/SVG markers, the Markers panel, menus and legend.

Built-in icons are original vector drawings made with QPainter (no third-party
artwork), so they stay sharp at every zoom level and in PNG/SVG export.
Custom markers are validated by content, size-limited, identified by a hash of
their bytes, and embedded in the workbook metadata when the map is saved.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional

from PySide6.QtCore import (QByteArray, QMimeData, QObject, QPoint, QPointF, QRect, QRectF, QSize,
                            QSizeF, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QDrag, QFont, QIcon, QImage, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF, QTextOption)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox,
                               QDockWidget, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLayout, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from vmap.core.commands import SetMarkersCommand
from vmap.core.markers import (ARROWS, COLORS, CUSTOM_GROUP, FACES, GROUPS, MONTHS, SYMBOLS, TASKS,
                               TRAFFIC, WEEKDAYS, apply_marker, group_name, group_of, is_custom,
                               marker_name, sort_markers)
from vmap.core.model import Topic, Workbook
from vmap.i18n import tr

if TYPE_CHECKING:
    from vmap.ui.canvas.view import MapView

log = logging.getLogger(__name__)
MARKER_SIZE = 16.0             # scene units on the canvas
MARKER_GAP = 3.0
MARKER_MIME = "application/x-vmap-marker"
EMBED_KEY = "custom_markers"   # key in workbook.metadata
MAX_CUSTOM_BYTES = 512 * 1024
MAX_CUSTOM_MARKERS = 500


# ============================================================ vector artwork
# Every painter draws into a 16 x 16 unit box.
def _qc(c) -> QColor:
    return c if isinstance(c, QColor) else QColor(c)


def _pen(color, width: float = 1.0) -> QPen:
    pen = QPen(_qc(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _text(p: QPainter, rect: QRectF, text: str, color="#FFFFFF", px: int = 10) -> None:
    font = QFont()
    font.setPixelSize(px)
    font.setBold(True)
    p.setFont(font)
    p.setPen(_qc(color))
    p.drawText(rect, text, QTextOption(Qt.AlignmentFlag.AlignCenter))


def _disc(p: QPainter, fill, rim=None) -> None:
    c = _qc(fill)
    p.setPen(_pen(rim if rim is not None else c.darker(135), 0.9))
    p.setBrush(c)
    p.drawEllipse(QRectF(0.7, 0.7, 14.6, 14.6))


def _ngon(cx: float, cy: float, r: float, n: int, start: float = 0.0) -> QPolygonF:
    return QPolygonF([QPointF(cx + r * math.cos(math.radians(start + i * 360.0 / n)),
                              cy + r * math.sin(math.radians(start + i * 360.0 / n)))
                      for i in range(n)])


def _tick(p: QPainter) -> None:
    p.setPen(_pen("#FFFFFF", 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(4.4, 8.4))
    path.lineTo(7.0, 11.0)
    path.lineTo(11.8, 5.6)
    p.drawPath(path)


def _priority(n: int, color: str):
    fg = "#3E2723" if color == "#FDD835" else "#FFFFFF"

    def paint(p):
        _disc(p, color)
        _text(p, QRectF(0, 0.4, 16, 16), str(n), fg, 11)
    return paint


_INK = "#5D4037"


def _face(kind: str):
    def paint(p):
        fill = "#FF8A65" if kind == "angry" else "#FFCA28"
        _disc(p, fill, _qc(fill).darker(130))
        ink = _pen(_INK, 1.1)
        if kind == "boring":
            p.setPen(ink)
            p.drawLine(QPointF(4.6, 6.6), QPointF(6.8, 6.6))
            p.drawLine(QPointF(9.2, 6.6), QPointF(11.4, 6.6))
            p.drawLine(QPointF(5.6, 11.0), QPointF(10.4, 11.0))
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_qc(_INK))
        p.drawEllipse(QRectF(4.9, 5.2, 1.8, 2.3))
        p.drawEllipse(QRectF(9.3, 5.2, 1.8, 2.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "smile":
            p.setPen(ink)
            p.drawArc(QRectF(4.2, 5.0, 7.6, 6.6), 200 * 16, 140 * 16)
        elif kind in ("laugh", "surprise"):
            p.setPen(_pen(_INK, 0.8))
            p.setBrush(_qc("#8D2C1E"))
            if kind == "laugh":
                p.drawChord(QRectF(4.0, 6.4, 8.0, 6.4), 180 * 16, 180 * 16)
            else:
                p.drawEllipse(QRectF(6.6, 9.4, 2.8, 3.4))
        else:  # angry / cry
            p.setPen(ink)
            p.drawArc(QRectF(4.8, 9.8, 6.4, 4.6), 20 * 16, 140 * 16)
            if kind == "angry":
                p.drawLine(QPointF(4.3, 4.0), QPointF(7.0, 5.0))
                p.drawLine(QPointF(11.7, 4.0), QPointF(9.0, 5.0))
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_qc("#29B6F6"))
                drop = QPainterPath(QPointF(11.6, 7.6))
                drop.cubicTo(12.9, 9.6, 13.0, 10.9, 11.6, 11.1)
                drop.cubicTo(10.2, 10.9, 10.3, 9.6, 11.6, 7.6)
                p.drawPath(drop)
    return paint


def _task(value):
    def paint(p):
        if value == "done":
            _disc(p, "#43A047")
            _tick(p)
            return
        if value == "pause":
            _disc(p, "#FB8C00")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qc("#FFFFFF"))
            p.drawRoundedRect(QRectF(4.9, 4.4, 2.3, 7.2), 0.6, 0.6)
            p.drawRoundedRect(QRectF(8.8, 4.4, 2.3, 7.2), 0.6, 0.6)
            return
        ring = QRectF(0.9, 0.9, 14.2, 14.2)
        p.setPen(_pen("#607D8B", 1.1))
        p.setBrush(_qc("#FFFFFF"))
        p.drawEllipse(ring)
        if value:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qc("#43A047"))
            p.drawPie(ring.adjusted(1.7, 1.7, -1.7, -1.7), 90 * 16, -int(round(value * 5760)))
    return paint


def _flag(color: str):
    def paint(p):
        p.setPen(_pen("#5D4037", 1.3))
        p.drawLine(QPointF(3.2, 1.6), QPointF(3.2, 14.8))
        path = QPainterPath(QPointF(3.8, 2.4))
        path.cubicTo(6.6, 0.8, 9.6, 4.0, 13.8, 2.4)
        path.lineTo(13.8, 9.0)
        path.cubicTo(9.6, 10.6, 6.6, 7.4, 3.8, 9.0)
        path.closeSubpath()
        p.setPen(_pen(_qc(color).darker(140), 0.8))
        p.setBrush(_qc(color))
        p.drawPath(path)
    return paint


def _star(color: str):
    def paint(p):
        pts = []
        for i in range(10):
            r = 7.4 if i % 2 == 0 else 3.0
            a = -math.pi / 2 + i * math.pi / 5
            pts.append(QPointF(8 + r * math.cos(a), 8.6 + r * math.sin(a)))
        p.setPen(_pen(_qc(color).darker(145), 0.9))
        p.setBrush(_qc(color))
        p.drawPolygon(QPolygonF(pts))
    return paint


def _person(color: str):
    def paint(p):
        c = _qc(color)
        p.setPen(_pen(c.darker(145), 0.8))
        p.setBrush(c)
        p.drawEllipse(QRectF(5.0, 1.2, 6.0, 6.0))
        body = QPainterPath(QPointF(1.8, 15.0))
        body.cubicTo(1.8, 8.4, 14.2, 8.4, 14.2, 15.0)
        body.closeSubpath()
        p.drawPath(body)
    return paint


def _arrow(angle):
    def paint(p):
        _disc(p, "#1E88E5")
        p.translate(8, 8)
        if angle is None:  # refresh
            p.setPen(_pen("#FFFFFF", 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(-4.2, -4.2, 8.4, 8.4), 40 * 16, 280 * 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qc("#FFFFFF"))
            p.drawPolygon(QPolygonF([QPointF(1.2, -4.6), QPointF(5.6, -4.6), QPointF(3.9, -0.6)]))
            return
        p.rotate(angle)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_qc("#FFFFFF"))
        p.drawPolygon(QPolygonF([QPointF(-4.6, -1.3), QPointF(0.8, -1.3), QPointF(0.8, -4.0),
                                 QPointF(5.2, 0.0), QPointF(0.8, 4.0), QPointF(0.8, 1.3),
                                 QPointF(-4.6, 1.3)]))
    return paint


_SYMBOL_COLORS = {"plus": "#43A047", "minus": "#E53935", "question": "#1E88E5",
                  "exclam": "#FB8C00", "info": "#039BE5", "wrong": "#E53935", "right": "#43A047"}


def _symbol(kind: str):
    def paint(p):
        _disc(p, _SYMBOL_COLORS[kind])
        white = _pen("#FFFFFF", 1.9)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind in ("plus", "minus"):
            p.setPen(white)
            p.drawLine(QPointF(4.4, 8), QPointF(11.6, 8))
            if kind == "plus":
                p.drawLine(QPointF(8, 4.4), QPointF(8, 11.6))
        elif kind == "wrong":
            p.setPen(white)
            p.drawLine(QPointF(5.2, 5.2), QPointF(10.8, 10.8))
            p.drawLine(QPointF(10.8, 5.2), QPointF(5.2, 10.8))
        elif kind == "right":
            _tick(p)
        else:
            glyph = {"question": "?", "exclam": "!", "info": "i"}[kind]
            _text(p, QRectF(0, 0.4, 16, 16), glyph, "#FFFFFF", 11)
    return paint


def _traffic(kind: str):
    def paint(p):
        if kind == "stop":
            p.setPen(_pen("#FFFFFF", 0.8))
            p.setBrush(_qc("#D32F2F"))
            p.drawPolygon(_ngon(8, 8, 7.6, 8, 22.5))
            p.setPen(_pen("#FFFFFF", 0.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(_ngon(8, 8, 6.3, 8, 22.5))
            _text(p, QRectF(0, 0, 16, 16), "STOP", "#FFFFFF", 4)
        elif kind == "yield":
            p.setPen(_pen("#D32F2F", 1.8))
            p.setBrush(_qc("#FFFFFF"))
            p.drawPolygon(QPolygonF([QPointF(1.6, 2.4), QPointF(14.4, 2.4), QPointF(8, 14.0)]))
        elif kind == "no-entry":
            _disc(p, "#D32F2F")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_qc("#FFFFFF"))
            p.drawRect(QRectF(3.4, 6.8, 9.2, 2.4))
        elif kind == "warning":
            p.setPen(_pen("#424242", 0.9))
            p.setBrush(_qc("#FDD835"))
            p.drawPolygon(QPolygonF([QPointF(8, 1.2), QPointF(15.0, 14.2), QPointF(1.0, 14.2)]))
            _text(p, QRectF(0, 4.2, 16, 10), "!", "#212121", 9)
        else:  # light-red / light-yellow / light-green
            lit = kind.split("-", 1)[1]
            p.setPen(_pen("#263238", 0.8))
            p.setBrush(_qc("#37474F"))
            p.drawRoundedRect(QRectF(4.4, 0.6, 7.2, 14.8), 1.8, 1.8)
            p.setPen(Qt.PenStyle.NoPen)
            for name, cy, on in (("red", 3.4, "#FF1744"), ("yellow", 8.0, "#FFD600"),
                                 ("green", 12.6, "#00E676")):
                p.setBrush(_qc(on if name == lit else "#607D8B"))
                p.drawEllipse(QPointF(8, cy), 1.8, 1.8)
    return paint


def _calendar(header: Optional[str], color: str, body: str, body_px: int):
    def paint(p):
        page = QRectF(1.2, 2.0, 13.6, 13.2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_qc("#FFFFFF"))
        p.drawRoundedRect(page, 1.8, 1.8)
        p.save()
        p.setClipRect(QRectF(0, 0, 16, 6.4))
        p.setBrush(_qc(color))
        p.drawRoundedRect(page, 1.8, 1.8)
        p.restore()
        p.setPen(_pen("#90A4AE", 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(page, 1.8, 1.8)
        p.setPen(_pen("#455A64", 1.1))
        p.drawLine(QPointF(4.8, 0.8), QPointF(4.8, 3.2))
        p.drawLine(QPointF(11.2, 0.8), QPointF(11.2, 3.2))
        if header:
            _text(p, QRectF(1.2, 2.5, 13.6, 3.8), header, "#FFFFFF", 4)
        _text(p, QRectF(1.2, 6.4, 13.6, 8.8), body, "#37474F", body_px)
    return paint


def _paint_unknown(p: QPainter) -> None:
    pen = _pen("#9E9E9E", 0.9)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(1.2, 1.2, 13.6, 13.6), 2.5, 2.5)
    _text(p, QRectF(0, 0, 16, 16), "?", "#757575", 10)


_PALETTE = {"red": "#E53935", "orange": "#FB8C00", "yellow": "#FDD835", "green": "#43A047",
            "blue": "#1E88E5", "purple": "#8E24AA", "gray": "#9E9E9E"}
_PRIORITY = ("#E53935", "#FB8C00", "#FDD835", "#43A047", "#1E88E5", "#8E24AA", "#6D4C41",
             "#546E7A", "#9E9E9E")
_TASK_VALUES = {"start": 0.0, "oct": 1 / 8, "quarter": 0.25, "3oct": 3 / 8, "half": 0.5,
                "5oct": 5 / 8, "3quar": 0.75, "7oct": 7 / 8, "done": "done", "pause": "pause"}
_ARROW_ANGLES = {"up": 270, "up-right": 315, "right": 0, "down-right": 45, "down": 90,
                 "down-left": 135, "left": 180, "up-left": 225, "refresh": None}


def _build_painters() -> dict[str, Callable[[QPainter], None]]:
    p: dict[str, Callable[[QPainter], None]] = {}
    for n, color in enumerate(_PRIORITY, 1):
        p[f"priority-{n}"] = _priority(n, color)
    for kind in FACES:
        p[f"smiley-{kind}"] = _face(kind)
    for kind in TASKS:
        p[f"task-{kind}"] = _task(_TASK_VALUES[kind])
    for name in COLORS:
        p[f"flag-{name}"] = _flag(_PALETTE[name])
        p[f"star-{name}"] = _star(_PALETTE[name])
        p[f"people-{name}"] = _person(_PALETTE[name])
    for kind in ARROWS:
        p[f"arrow-{kind}"] = _arrow(_ARROW_ANGLES[kind])
    for kind in SYMBOLS:
        p[f"symbol-{kind}"] = _symbol(kind)
    for kind in TRAFFIC:
        p[f"traffic-{kind}"] = _traffic(kind)
    for i, month in enumerate(MONTHS, 1):
        p[f"month-{month}"] = _calendar(month.upper(), "#E53935", str(i), 8)
    for day in WEEKDAYS:
        color = "#E53935" if day in ("sat", "sun") else "#1E88E5"
        p[f"week-{day}"] = _calendar(None, color, day[:2].capitalize(), 7)
    return p


_PAINTERS = _build_painters()


def paint_marker(painter: QPainter, rect: QRectF, marker_id: str,
                 library: Optional["MarkerLibrary"] = None) -> None:
    """Draw one marker into rect (canvas, export, icons)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    try:
        if library is not None and is_custom(marker_id) and library.paint(marker_id, painter, rect):
            return
        painter.translate(rect.topLeft())
        painter.scale(rect.width() / 16.0, rect.height() / 16.0)
        _PAINTERS.get(marker_id, _paint_unknown)(painter)
    finally:
        painter.restore()


def marker_icon(marker_id: str, size: int = 20,
                library: Optional["MarkerLibrary"] = None) -> QIcon:
    icon = QIcon()
    for dpr in (1.0, 2.0):
        px = max(1, int(size * dpr))
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        paint_marker(p, QRectF(0, 0, px, px), marker_id, library)
        p.end()
        pm.setDevicePixelRatio(dpr)
        icon.addPixmap(pm)
    return icon


def marker_label(marker_id: str, library: Optional["MarkerLibrary"] = None) -> str:
    if is_custom(marker_id):
        name = library.name(marker_id) if library is not None else None
        return name or tr("Missing custom marker")
    return marker_name(marker_id)


# ============================================================ custom markers
def _fit(rect: QRectF, size: QSizeF) -> QRectF:
    if size.width() <= 0 or size.height() <= 0:
        return QRectF(rect)
    s = min(rect.width() / size.width(), rect.height() / size.height())
    w, h = size.width() * s, size.height() * s
    return QRectF(rect.x() + (rect.width() - w) / 2, rect.y() + (rect.height() - h) / 2, w, h)


def _sniff(data: bytes) -> Optional[str]:
    """PNG or SVG by content, never by file extension."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    head = data[:65536].lower()
    start = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if start.startswith((b"<?xml", b"<svg", b"<!--", b"<!doctype")) and b"<svg" in head:
        return "svg"
    return None


def _decodes(data: bytes, fmt: str) -> bool:
    if fmt == "svg":
        return QSvgRenderer(QByteArray(data)).isValid()
    image = QImage()
    return bool(image.loadFromData(QByteArray(data))) and not image.isNull()


def _clean_name(name: Any, fallback: str) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(name)).strip()
    return text[:64] or fallback


@dataclass(eq=False)
class CustomMarker:
    id: str
    name: str
    group: str
    fmt: str
    data: bytes = field(repr=False)
    persisted: bool = False
    _renderer: Any = field(default=None, repr=False)

    def paint(self, painter: QPainter, rect: QRectF) -> bool:
        if self._renderer is None:
            if self.fmt == "svg":
                self._renderer = QSvgRenderer(QByteArray(self.data))
            else:
                image = QImage()
                image.loadFromData(QByteArray(self.data))
                self._renderer = image
        r = self._renderer
        if isinstance(r, QSvgRenderer):
            if not r.isValid():
                return False
            r.render(painter, _fit(rect, QSizeF(r.defaultSize())))
            return True
        if r.isNull():
            return False
        painter.drawImage(_fit(rect, QSizeF(r.size())), r)
        return True


class MarkerLibrary(QObject):
    """Custom PNG/SVG markers: a per-user library on disk plus copies embedded in maps."""
    changed = Signal()

    def __init__(self, user_dir: Optional[Path] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.user_dir = Path(user_dir) if user_dir else None
        self._markers: dict[str, CustomMarker] = {}
        self._groups: list[str] = []

    # ---------------------------------------------------------------- queries
    def has(self, marker_id: str) -> bool:
        return marker_id in self._markers

    def get(self, marker_id: str) -> Optional[CustomMarker]:
        return self._markers.get(marker_id)

    def name(self, marker_id: str) -> Optional[str]:
        m = self._markers.get(marker_id)
        return m.name if m is not None else None

    def groups(self) -> list[tuple[str, list[CustomMarker]]]:
        return [(g, [m for m in self._markers.values() if m.group == g]) for g in self._groups]

    def paint(self, marker_id: str, painter: QPainter, rect: QRectF) -> bool:
        m = self._markers.get(marker_id)
        return m is not None and m.paint(painter, QRectF(rect))

    # --------------------------------------------------------------- adding
    def _group(self, name: str) -> str:
        name = _clean_name(name, tr("Custom"))
        for g in self._groups:
            if g.casefold() == name.casefold():
                return g
        self._groups.append(name)
        return name

    def _register(self, data: Any, name: str, group: str, persisted: bool,
                  expected_id: Any = None) -> tuple[str, bool]:
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError(tr("no image data"))
        data = bytes(data)
        if len(data) > MAX_CUSTOM_BYTES:
            raise ValueError(tr("larger than {n} KB").format(n=MAX_CUSTOM_BYTES // 1024))
        fmt = _sniff(data)
        if fmt is None:
            raise ValueError(tr("not a PNG or SVG image"))
        marker_id = "custom:" + hashlib.sha256(data).hexdigest()[:16]
        if expected_id is not None and expected_id != marker_id:
            raise ValueError(tr("marker id does not match the image data"))
        existing = self._markers.get(marker_id)
        if existing is not None:
            existing.persisted = existing.persisted or persisted
            return marker_id, False
        if len(self._markers) >= MAX_CUSTOM_MARKERS:
            raise ValueError(tr("too many custom markers"))
        if not _decodes(data, fmt):
            raise ValueError(tr("the image could not be decoded"))
        self._markers[marker_id] = CustomMarker(marker_id, _clean_name(name, tr("Marker")),
                                                self._group(group), fmt, data, persisted)
        return marker_id, True

    def add_files(self, paths: Iterable[Any], group: str) -> tuple[list[str], list[str]]:
        """Import PNG/SVG files into the user library. Returns (added ids, error lines)."""
        added: list[str] = []
        errors: list[str] = []
        for path in map(Path, paths):
            try:
                if path.stat().st_size > MAX_CUSTOM_BYTES:
                    raise ValueError(tr("larger than {n} KB").format(n=MAX_CUSTOM_BYTES // 1024))
                marker_id, _ = self._register(path.read_bytes(), path.stem, group, True)
                added.append(marker_id)
            except (OSError, ValueError) as exc:
                errors.append(f"{path.name}: {exc}")
        if added:
            self.save()
            self.changed.emit()
        return added, errors

    # ------------------------------------------------------------- editing
    def _changed(self) -> None:
        self.save()
        self.changed.emit()

    def _delete_file(self, m: CustomMarker) -> None:
        if m.persisted and self.user_dir is not None:
            try:
                (self.user_dir / f"{m.id.split(':', 1)[1]}.{m.fmt}").unlink()
            except OSError:
                pass

    def rename(self, marker_id: str, name: str) -> None:
        m = self._markers.get(marker_id)
        if m is not None:
            m.name = _clean_name(name, m.name)
            self._changed()

    def keep(self, marker_id: str) -> None:
        """Copy a marker that came with a map into the user library."""
        m = self._markers.get(marker_id)
        if m is not None and not m.persisted:
            m.persisted = True
            self._changed()

    def remove(self, marker_id: str) -> None:
        m = self._markers.pop(marker_id, None)
        if m is None:
            return
        self._delete_file(m)
        if not any(x.group == m.group for x in self._markers.values()):
            self._groups = [g for g in self._groups if g != m.group]
        self._changed()

    def rename_group(self, old: str, new: str) -> None:
        new = _clean_name(new, old)
        target = next((g for g in self._groups if g.casefold() == new.casefold() and g != old), new)
        for m in self._markers.values():
            if m.group == old:
                m.group = target
        self._groups = list(dict.fromkeys(target if g == old else g for g in self._groups))
        self._changed()

    def remove_group(self, name: str) -> None:
        for marker_id in [m.id for m in self._markers.values() if m.group == name]:
            self._delete_file(self._markers.pop(marker_id))
        self._groups = [g for g in self._groups if g != name]
        self._changed()

    # ---------------------------------------------------------- embedding
    def export_embedded(self, ids: Iterable[str]) -> list[dict[str, Any]]:
        out = []
        for marker_id in ids:
            m = self._markers.get(marker_id)
            if m is not None:
                out.append({"id": m.id, "name": m.name, "group": m.group, "format": m.fmt,
                            "data": base64.b64encode(m.data).decode("ascii")})
        return out

    def import_embedded(self, items: Any) -> list[str]:
        """Register custom markers found in an (untrusted) map. Returns warnings."""
        if items is None:
            return []
        if not isinstance(items, list):
            return [tr("Embedded custom markers ignored: invalid data.")]
        warnings: list[str] = []
        added = 0
        for item in items[:MAX_CUSTOM_MARKERS]:
            try:
                if not isinstance(item, dict):
                    raise ValueError(tr("invalid entry"))
                encoded = item.get("data")
                if not isinstance(encoded, str) or len(encoded) > MAX_CUSTOM_BYTES * 4 // 3 + 8:
                    raise ValueError(tr("missing or oversized image data"))
                data = base64.b64decode(encoded, validate=True)
                _, new = self._register(data, str(item.get("name") or ""),
                                        str(item.get("group") or tr("From Map")), False,
                                        expected_id=item.get("id"))
                added += int(new)
            except ValueError as exc:      # binascii.Error is a ValueError
                warnings.append(tr("Embedded custom marker ignored: {e}").format(e=exc))
        if added:
            self.changed.emit()
        return warnings

    # -------------------------------------------------------- user library
    def save(self) -> None:
        if self.user_dir is None:
            return
        entries = []
        tmp: Optional[Path] = None
        try:
            self.user_dir.mkdir(parents=True, exist_ok=True)
            for m in self._markers.values():
                if not m.persisted:
                    continue
                file_name = f"{m.id.split(':', 1)[1]}.{m.fmt}"
                target = self.user_dir / file_name
                if not target.exists():
                    target.write_bytes(m.data)
                entries.append({"id": m.id, "name": m.name, "group": m.group, "file": file_name})
            index = self.user_dir / "markers.json"
            tmp = index.with_name(f".{index.name}.{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps({"version": 1, "markers": entries}, ensure_ascii=False,
                                      indent=2), encoding="utf-8")
            os.replace(tmp, index)
        except OSError as exc:
            log.warning("could not save custom markers: %s", exc)
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()

    def load(self) -> list[str]:
        """Load the user library. Returns warnings (for the Diagnostics dialog)."""
        if self.user_dir is None:
            return []
        index = self.user_dir / "markers.json"
        if not index.is_file():
            return []
        try:
            meta = json.loads(index.read_text(encoding="utf-8"))
            entries = meta.get("markers") if isinstance(meta, dict) else None
            if not isinstance(entries, list):
                raise ValueError("markers must be a list")
        except (OSError, ValueError) as exc:
            return [tr("Custom markers not loaded: {e}").format(e=exc)]
        warnings: list[str] = []
        loaded = 0
        for entry in entries[:MAX_CUSTOM_MARKERS]:
            try:
                if not isinstance(entry, dict):
                    raise ValueError(tr("invalid entry"))
                path = self.user_dir / Path(str(entry.get("file", ""))).name  # stays in the folder
                _, new = self._register(path.read_bytes(), str(entry.get("name") or path.stem),
                                        str(entry.get("group") or ""), True,
                                        expected_id=entry.get("id"))
                loaded += int(new)
            except (OSError, ValueError) as exc:
                warnings.append(tr("Custom marker skipped: {e}").format(e=exc))
        if loaded:
            self.changed.emit()
        return warnings


def embed_custom_markers(workbook: Workbook, library: MarkerLibrary) -> None:
    """Copy the custom images a workbook uses into its metadata (called just before saving).

    Derived data, like the modified stamp: it is refreshed on every save and is not an
    undo step. Previously embedded images whose marker is still used are kept even if
    this machine's library lacks them.
    """
    used = {m for sheet in workbook.sheets for t in sheet.topics() for m in t.markers
            if is_custom(m)}
    items = library.export_embedded(sorted(used))
    have = {item["id"] for item in items}
    old = workbook.metadata.get(EMBED_KEY)
    if isinstance(old, list):
        items += [i for i in old if isinstance(i, dict) and i.get("id") in used
                  and i.get("id") not in have]
    if items:
        workbook.metadata[EMBED_KEY] = items
    else:
        workbook.metadata.pop(EMBED_KEY, None)


# ============================================================ menus helpers
def _add(menu: QMenu, text: str, slot: Callable[[], Any], marker_id: Optional[str] = None,
         library: Optional[MarkerLibrary] = None, enabled: bool = True,
         checked: Optional[bool] = None):
    action = menu.addAction(text)
    if marker_id is not None:
        action.setIcon(marker_icon(marker_id, 16, library))
    action.setEnabled(enabled)
    if checked is not None:
        action.setCheckable(True)
        action.setChecked(checked)
    action.triggered.connect(lambda checked=False, fn=slot: fn())
    return action


def _menu_text(text: str) -> str:
    return text.replace("&", "&&")


# ============================================================ controller
class MarkerController(QObject):
    """XMind-like marker behaviour. Every change is one undoable SetMarkersCommand."""

    def __init__(self, view: "MapView", library: MarkerLibrary, run: Callable[[Any], bool],
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.view, self.library, self._run = view, library, run

    # ------------------------------------------------------------- editing
    def apply(self, topics: Iterable[Topic], marker_id: str, mode: str = "toggle") -> bool:
        """mode 'toggle' removes the marker if every topic has it, otherwise adds it."""
        topics = [t for t in topics if self.view.in_sheet(t)]
        if not topics:
            self.view.message.emit(tr("Select one or more topics first."))
            return False
        if mode == "toggle":
            mode = "remove" if all(marker_id in t.markers for t in topics) else "add"
        try:
            changes = [(t, apply_marker(t.markers, marker_id, mode)) for t in topics]
        except ValueError as exc:
            self.view.message.emit(str(exc))
            return False
        changes = [(t, new) for t, new in changes if new != t.markers]
        if not changes:
            return False
        label = tr("Remove Marker") if mode == "remove" else tr("Add Marker")
        return self._run(SetMarkersCommand(changes, label=label))

    def toggle(self, marker_id: str) -> None:
        self.apply(self.view.selected_topics(), marker_id, "toggle")

    def clear(self, topics: Optional[Iterable[Topic]] = None) -> None:
        topics = self.view.selected_topics() if topics is None else list(topics)
        changes = [(t, []) for t in topics if t.markers]
        if changes:
            self._run(SetMarkersCommand(changes, label=tr("Remove All Markers")))

    def topics_with(self, marker_id: str) -> list[Topic]:
        sheet = self.view.sheet
        return [t for t in sheet.topics() if marker_id in t.markers] if sheet else []

    def usage(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        sheet = self.view.sheet
        for t in (sheet.topics() if sheet else ()):
            for marker_id in set(t.markers):
                counts[marker_id] = counts.get(marker_id, 0) + 1
        return counts

    def select_with(self, marker_id: str) -> None:
        topics = self.topics_with(marker_id)
        visible = [t for t in topics if self.view.scene_.item_for(t) is not None]
        self.view.select_topics(visible)
        text = tr("{n} topic(s) selected.").format(n=len(visible))
        if len(topics) > len(visible):
            text += " " + tr("{n} more are inside collapsed branches.").format(
                n=len(topics) - len(visible))
        self.view.message.emit(text)

    def replace_everywhere(self, old: str, new: str) -> None:
        try:
            changes = [(t, apply_marker(apply_marker(t.markers, old, "remove"), new, "add"))
                       for t in self.topics_with(old)]
        except ValueError as exc:
            self.view.message.emit(str(exc))
            return
        if changes:
            self._run(SetMarkersCommand(changes, label=tr("Replace Marker")))

    def remove_everywhere(self, marker_id: str) -> None:
        topics = self.topics_with(marker_id)
        if topics:
            self.apply(topics, marker_id, "remove")

    # --------------------------------------------------------------- menus
    def build_menu(self, parent: Optional[QWidget] = None, title: Optional[str] = None) -> QMenu:
        """Markers menu for the Insert menu or a context menu (rebuilt each time it opens)."""
        menu = QMenu(title or tr("&Markers"), parent)
        menu.aboutToShow.connect(lambda m=menu: self._fill_menu(m))
        return menu

    def _sections(self) -> list[tuple[str, list[str]]]:
        sections = [(group_name(gid), list(ids)) for gid, _, ids in GROUPS]
        sections += [(name, [m.id for m in items]) for name, items in self.library.groups()
                     if items]
        return sections

    def _fill_menu(self, menu: QMenu) -> None:
        for sub in menu.findChildren(QMenu):
            sub.deleteLater()
        menu.clear()
        topics = self.view.selected_topics()
        common = set.intersection(*(set(t.markers) for t in topics)) if topics else set()
        for title, ids in self._sections():
            sub = menu.addMenu(marker_icon(ids[0], 16, self.library), _menu_text(title))
            for marker_id in ids:
                _add(sub, _menu_text(marker_label(marker_id, self.library)),
                     lambda m=marker_id: self.toggle(m), marker_id, self.library,
                     enabled=bool(topics), checked=marker_id in common)
        menu.addSeparator()
        _add(menu, tr("Remove All Markers"), self.clear, enabled=any(t.markers for t in topics))
        menu.addSeparator()
        _add(menu, tr("Marker Legend\u2026"), lambda: self.show_legend(self.view.window()))
        _add(menu, tr("Add Custom Markers\u2026"),
             lambda: self.add_custom_dialog(self.view.window()))

    def show_popup(self, topic: Topic, marker_id: str, global_pos: QPoint) -> None:
        """Clicking a marker on a topic: switch within its group, remove, select alike."""
        if not self.view.in_sheet(topic) or marker_id not in topic.markers:
            return
        menu = QMenu(self.view)
        group = group_of(marker_id)
        title, siblings = "", []
        if group == CUSTOM_GROUP:
            custom = self.library.get(marker_id)
            if custom is not None:
                title = custom.group
                siblings = [m.id for name, items in self.library.groups()
                            if name == custom.group for m in items]
        elif group is not None:
            title = group_name(group)
            siblings = next(list(ids) for gid, _, ids in GROUPS if gid == group)
        if siblings:
            menu.addAction(_menu_text(title)).setEnabled(False)
            for other in siblings:
                _add(menu, _menu_text(marker_label(other, self.library)),
                     lambda m=other: self.apply([topic], m, "toggle"), other, self.library,
                     checked=other in topic.markers)
            menu.addSeparator()
        _add(menu, tr("Remove This Marker"), lambda: self.apply([topic], marker_id, "remove"))
        _add(menu, tr("Remove All Markers From Topic"), lambda: self.clear([topic]))
        menu.addSeparator()
        _add(menu, tr("Select All Topics With This Marker"), lambda: self.select_with(marker_id))
        menu.exec(global_pos)
        menu.deleteLater()

    def show_legend(self, parent: Optional[QWidget] = None) -> None:
        LegendDialog(self, parent).exec()

    # ------------------------------------------------------ custom markers
    def add_custom_files(self, files: Iterable[Any], parent: Optional[QWidget] = None,
                         group: Optional[str] = None) -> list[str]:
        files = [str(f) for f in files]
        if not files:
            return []
        if group is None:
            names = [name for name, _ in self.library.groups()] or [tr("Custom")]
            group, ok = QInputDialog.getItem(
                parent, tr("Custom Markers"), tr("Add to group (type a new name to create one):"),
                names, 0, True)
            if not ok or not group.strip():
                return []
        added, errors = self.library.add_files(files, group)
        if errors:
            QMessageBox.warning(parent, tr("Custom Markers"),
                                tr("Some files were skipped:") + "\n\n" + "\n".join(errors[:20]))
        if added and self.library.user_dir is None:
            self.view.message.emit(tr("No writable data folder: custom markers are kept for "
                                      "this session only."))
        return added

    def add_custom_dialog(self, parent: Optional[QWidget] = None,
                          group: Optional[str] = None) -> list[str]:
        files, _ = QFileDialog.getOpenFileNames(parent, tr("Add Custom Markers"), "",
                                                tr("Marker Images (*.png *.svg)"))
        return self.add_custom_files(files, parent, group)

    def import_folder_dialog(self, parent: Optional[QWidget] = None) -> list[str]:
        folder = QFileDialog.getExistingDirectory(parent, tr("Import Folder as Marker Group"))
        if not folder:
            return []
        files = sorted(p for p in Path(folder).iterdir()
                       if p.is_file() and p.suffix.lower() in (".png", ".svg"))[:200]
        if not files:
            QMessageBox.information(parent, tr("Custom Markers"),
                                    tr("That folder contains no PNG or SVG files."))
            return []
        return self.add_custom_files(files, parent, Path(folder).name)


# ============================================================ legend
class LegendDialog(QDialog):
    """Markers used on the current sheet, with counts and sheet-wide actions."""

    def __init__(self, controller: MarkerController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.c = controller
        self.setWindowTitle(tr("Marker Legend"))
        self.resize(520, 380)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Marker"), tr("Group"), tr("Topics")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        row = QHBoxLayout()
        for text, slot in ((tr("Select Topics"), self._select),
                           (tr("Replace With\u2026"), self._replace),
                           (tr("Remove From Sheet"), self._remove)):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, fn=slot: fn())
            row.addWidget(button)
        row.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        row.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        layout.addLayout(row)
        self._fill()

    def _fill(self) -> None:
        self.tree.clear()
        usage = self.c.usage()
        for marker_id in sort_markers(usage):
            custom = self.c.library.get(marker_id)
            group = group_of(marker_id)
            group_label = (custom.group if custom is not None
                           else group_name(group) if group else tr("Unknown"))
            item = QTreeWidgetItem([marker_label(marker_id, self.c.library), group_label,
                                    str(usage[marker_id])])
            item.setIcon(0, marker_icon(marker_id, 18, self.c.library))
            item.setData(0, Qt.ItemDataRole.UserRole, marker_id)
            self.tree.addTopLevelItem(item)
        for column in range(3):
            self.tree.resizeColumnToContents(column)

    def _current(self) -> Optional[str]:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None

    def _select(self) -> None:
        marker_id = self._current()
        if marker_id:
            self.c.select_with(marker_id)

    def _replace(self) -> None:
        old = self._current()
        if not old:
            return
        choices: dict[str, str] = {}
        for gid, _, ids in GROUPS:
            for marker_id in ids:
                choices[f"{group_name(gid)} \u2014 {marker_name(marker_id)}"] = marker_id
        for name, items in self.c.library.groups():
            for m in items:
                choices[f"{name} \u2014 {m.name}"] = m.id
        choices = {k: v for k, v in choices.items() if v != old}
        label, ok = QInputDialog.getItem(self, tr("Replace Marker"), tr("Replace with:"),
                                         list(choices), 0, False)
        if ok and label in choices:
            self.c.replace_everywhere(old, choices[label])
            self._fill()

    def _remove(self) -> None:
        marker_id = self._current()
        if not marker_id:
            return
        question = tr("Remove \u201c{name}\u201d from every topic on this sheet?").format(
            name=marker_label(marker_id, self.c.library))
        if QMessageBox.question(self, tr("Remove Marker"), question) == \
                QMessageBox.StandardButton.Yes:
            self.c.remove_everywhere(marker_id)
            self._fill()


# ============================================================ Markers panel
class FlowLayout(QLayout):
    """Wrapping layout for the marker buttons."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(4, 2, 4, 6)
        self.setSpacing(2)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h, gap = r.x(), r.y(), 0, self.spacing()
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x > r.x() and x + hint.width() > r.right() + 1:
                x, y, line_h = r.x(), y + line_h + gap, 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class _MarkerButton(QToolButton):
    def __init__(self, marker_id: str, label: str, controller: MarkerController) -> None:
        super().__init__()
        self.marker_id, self.label = marker_id, label
        self._press: Optional[QPoint] = None
        self.setIcon(marker_icon(marker_id, 22, controller.library))
        self.setIconSize(QSize(22, 22))
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # keep keyboard focus (and F4) on the map
        self.setToolTip(label)
        self.clicked.connect(lambda checked=False: controller.toggle(self.marker_id))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self._press is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            self.setDown(False)
            mime = QMimeData()
            mime.setData(MARKER_MIME, QByteArray(self.marker_id.encode("utf-8")))
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.icon().pixmap(QSize(24, 24)))
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press = None
        super().mouseReleaseEvent(event)


class MarkersPanel(QDockWidget):
    """XMind-style Markers view: click toggles a marker on the selection; drag onto a topic."""

    def __init__(self, controller: MarkerController, parent: Optional[QWidget] = None) -> None:
        super().__init__(tr("Markers"), parent)
        self.setObjectName("markersDock")
        self.c, self.lib = controller, controller.library
        self._collapsed: set[str] = set()
        self._sections: list[tuple[QWidget, QToolButton, QWidget, list[_MarkerButton], str]] = []
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search markers\u2026"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._apply_search())
        more = QToolButton()
        more.setText("\u22ef")
        more.setToolTip(tr("More marker actions"))
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        _add(menu, tr("Add Custom Markers\u2026"), lambda: self.c.add_custom_dialog(self))
        _add(menu, tr("Import Folder as Marker Group\u2026"),
             lambda: self.c.import_folder_dialog(self))
        _add(menu, tr("Open Custom Markers Folder"), self._open_folder,
             enabled=self.lib.user_dir is not None)
        menu.addSeparator()
        _add(menu, tr("Marker Legend\u2026"), lambda: self.c.show_legend(self))
        _add(menu, tr("Remove All Markers From Selection"), self.c.clear)
        more.setMenu(menu)
        bar.addWidget(self.search, 1)
        bar.addWidget(more)
        outer.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.sections = QVBoxLayout(self.content)
        self.sections.setContentsMargins(0, 0, 0, 0)
        self.sections.setSpacing(2)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)
        tip = QLabel(tr("Click: add or remove on the selected topics. Drag: drop onto a topic. "
                        "Drop PNG/SVG files here to add custom markers."))
        tip.setWordWrap(True)
        tip.setStyleSheet("color: palette(mid); font-size: 11px;")
        outer.addWidget(tip)
        self.setWidget(root)
        self.setAcceptDrops(True)
        self.lib.changed.connect(self.rebuild)
        self.rebuild()

    # ---------------------------------------------------------------- build
    def rebuild(self) -> None:
        while self.sections.count():
            widget = self.sections.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._sections = []
        for gid, _, ids in GROUPS:
            self._add_section(gid, group_name(gid), [(m, marker_name(m)) for m in ids], False)
        for name, items in self.lib.groups():
            self._add_section("custom/" + name, name, [(m.id, m.name) for m in items], True)
        self.sections.addStretch(1)
        self._apply_search()

    def _add_section(self, key: str, title: str, markers: list[tuple[str, str]],
                     custom: bool) -> None:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        head = QToolButton()
        head.setText(title)
        head.setCheckable(True)
        head.setChecked(key not in self._collapsed)
        head.setAutoRaise(True)
        head.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        head.setArrowType(Qt.ArrowType.DownArrow if head.isChecked() else Qt.ArrowType.RightArrow)
        head.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        font = head.font()
        font.setBold(True)
        head.setFont(font)
        body = QWidget()
        flow = FlowLayout(body)
        buttons: list[_MarkerButton] = []
        for marker_id, label in markers:
            button = _MarkerButton(marker_id, label, self.c)
            if custom:
                button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda pos, b=button: self._custom_menu(b, pos))
            flow.addWidget(button)
            buttons.append(button)
        body.setVisible(head.isChecked())
        head.toggled.connect(lambda on, k=key, h=head, b=body: self._toggle(k, h, b, on))
        if custom:
            head.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            head.customContextMenuRequested.connect(
                lambda pos, n=title, h=head: self._group_menu(n, h, pos))
        layout.addWidget(head)
        layout.addWidget(body)
        self.sections.addWidget(box)
        self._sections.append((box, head, body, buttons, title.casefold()))

    def _toggle(self, key: str, head: QToolButton, body: QWidget, on: bool) -> None:
        head.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        body.setVisible(on)
        if on:
            self._collapsed.discard(key)
        else:
            self._collapsed.add(key)

    def _apply_search(self) -> None:
        needle = self.search.text().strip().casefold()
        for box, head, body, buttons, title in self._sections:
            hits = 0
            for button in buttons:
                show = (not needle or needle in button.label.casefold() or needle in title
                        or needle in button.marker_id)
                button.setVisible(show)
                hits += int(show)
            box.setVisible(not needle or hits > 0)
            body.setVisible(head.isChecked() if not needle else hits > 0)

    # -------------------------------------------------------- custom markers
    def _custom_menu(self, button: _MarkerButton, pos: QPoint) -> None:
        custom = self.lib.get(button.marker_id)
        if custom is None:
            return
        marker_id = custom.id
        menu = QMenu(self)
        _add(menu, tr("Rename\u2026"), lambda: self._rename_marker(marker_id))
        if not custom.persisted:
            _add(menu, tr("Keep in My Markers"), lambda: self.lib.keep(marker_id))
        _add(menu, tr("Delete"), lambda: self._delete_marker(marker_id))
        menu.exec(button.mapToGlobal(pos))
        menu.deleteLater()

    def _group_menu(self, name: str, head: QToolButton, pos: QPoint) -> None:
        menu = QMenu(self)
        _add(menu, tr("Add Markers to This Group\u2026"),
             lambda: self.c.add_custom_dialog(self, name))
        _add(menu, tr("Rename Group\u2026"), lambda: self._rename_group(name))
        _add(menu, tr("Delete Group"), lambda: self._delete_group(name))
        menu.exec(head.mapToGlobal(pos))
        menu.deleteLater()

    def _rename_marker(self, marker_id: str) -> None:
        custom = self.lib.get(marker_id)
        if custom is None:
            return
        text, ok = QInputDialog.getText(self, tr("Rename Marker"), tr("Name:"),
                                        QLineEdit.EchoMode.Normal, custom.name)
        if ok and text.strip():
            self.lib.rename(marker_id, text)

    def _delete_marker(self, marker_id: str) -> None:
        question = tr("Delete \u201c{name}\u201d? Topics that use it show a placeholder until "
                      "the image is added again.").format(name=self.lib.name(marker_id))
        if QMessageBox.question(self, tr("Delete Marker"), question) == \
                QMessageBox.StandardButton.Yes:
            self.lib.remove(marker_id)

    def _rename_group(self, name: str) -> None:
        text, ok = QInputDialog.getText(self, tr("Rename Group"), tr("Name:"),
                                        QLineEdit.EchoMode.Normal, name)
        if ok and text.strip():
            self.lib.rename_group(name, text)

    def _delete_group(self, name: str) -> None:
        question = tr("Delete the group \u201c{name}\u201d and all its markers?").format(name=name)
        if QMessageBox.question(self, tr("Delete Group"), question) == \
                QMessageBox.StandardButton.Yes:
            self.lib.remove_group(name)

    def _open_folder(self) -> None:
        if self.lib.user_dir is None:
            return
        try:
            self.lib.user_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.lib.user_dir)))

    # ------------------------------------------ drop PNG/SVG files to import
    @staticmethod
    def _image_files(event) -> list[str]:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith((".png", ".svg"))]

    def dragEnterEvent(self, event) -> None:
        if self._image_files(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._image_files(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        files = self._image_files(event)
        if files:
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.c.add_custom_files(files, self))
        else:
            super().dropEvent(event)
