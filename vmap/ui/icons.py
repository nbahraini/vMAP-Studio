"""Toolbar and application icons drawn with QPainter.

No third-party or proprietary artwork is shipped; icons are generated at
runtime in the palette's text colour, so they follow light/dark mode.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

GRID = 24  # logical drawing grid for toolbar icons


def _path(*points: tuple[float, float], close: bool = False) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:
        path.lineTo(QPointF(*pt))
    if close:
        path.closeSubpath()
    return path


def _new(p: QPainter) -> None:
    p.drawPath(_path((6, 3), (14, 3), (19, 8), (19, 21), (6, 21), close=True))
    p.drawPath(_path((14, 3), (14, 8), (19, 8)))


def _open(p: QPainter) -> None:
    p.drawPath(_path((3, 6), (9, 6), (11, 8), (20, 8), (20, 19), (3, 19), close=True))
    p.drawLine(QPointF(3, 11), QPointF(20, 11))


def _save(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(4, 4, 16, 16), 2, 2)
    p.drawRect(QRectF(8, 4, 8, 5))
    p.drawRect(QRectF(7, 13, 10, 7))


def _undo(p: QPainter) -> None:
    path = QPainterPath(QPointF(19, 18))
    path.cubicTo(QPointF(19, 11), QPointF(14, 9), QPointF(6, 10))
    p.drawPath(path)
    p.drawPath(_path((9.5, 6.5), (6, 10), (9.5, 13.5)))


def _redo(p: QPainter) -> None:
    p.translate(GRID, 0)
    p.scale(-1, 1)
    _undo(p)


def _topic(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(9, 3, 12, 7), 2, 2)
    p.drawRoundedRect(QRectF(9, 14, 12, 7), 2, 2)
    p.drawPath(_path((9, 6.5), (5, 6.5), (5, 17.5), (9, 17.5)))


def _subtopic(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(2, 4, 10, 7), 2, 2)
    p.drawRoundedRect(QRectF(12, 14, 10, 7), 2, 2)
    p.drawPath(_path((7, 11), (7, 17.5), (12, 17.5)))


def _delete(p: QPainter) -> None:
    p.drawLine(QPointF(4, 6.5), QPointF(20, 6.5))
    p.drawPath(_path((9, 6.5), (9, 4), (15, 4), (15, 6.5)))
    p.drawPath(_path((6, 6.5), (7.5, 20), (16.5, 20), (18, 6.5)))
    p.drawLine(QPointF(10.5, 10), QPointF(10.5, 16.5))
    p.drawLine(QPointF(13.5, 10), QPointF(13.5, 16.5))


def _fold(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(2, 8.5, 10, 7), 2, 2)
    p.drawLine(QPointF(12, 12), QPointF(14.5, 12))
    p.drawEllipse(QPointF(18, 12), 3.5, 3.5)
    p.drawLine(QPointF(16.3, 12), QPointF(19.7, 12))


def _magnifier(p: QPainter) -> None:
    p.drawEllipse(QPointF(10, 10), 6, 6)
    p.drawLine(QPointF(14.5, 14.5), QPointF(20, 20))


def _zoom_in(p: QPainter) -> None:
    _magnifier(p)
    p.drawLine(QPointF(7, 10), QPointF(13, 10))
    p.drawLine(QPointF(10, 7), QPointF(10, 13))


def _zoom_out(p: QPainter) -> None:
    _magnifier(p)
    p.drawLine(QPointF(7, 10), QPointF(13, 10))


def _fit(p: QPainter) -> None:
    for x, y, dx, dy in ((4, 4, 1, 1), (20, 4, -1, 1), (4, 20, 1, -1), (20, 20, -1, -1)):
        p.drawPath(_path((x, y + 5 * dy), (x, y), (x + 5 * dx, y)))
    p.drawRoundedRect(QRectF(9, 10, 6, 4), 1, 1)


def _theme(p: QPainter) -> None:
    p.drawEllipse(QRectF(3, 4, 18, 16))
    p.save()
    p.setBrush(p.pen().color())
    for x, y in ((8, 9), (12, 7.5), (16, 9), (8, 14)):
        p.drawEllipse(QPointF(x, y), 1.3, 1.3)
    p.restore()


def _structure(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(8, 3, 8, 5), 1.5, 1.5)
    p.drawLine(QPointF(12, 8), QPointF(12, 12))
    p.drawPath(_path((5, 16), (5, 12), (19, 12), (19, 16)))
    p.drawRoundedRect(QRectF(2, 16, 6, 5), 1.5, 1.5)
    p.drawRoundedRect(QRectF(16, 16, 6, 5), 1.5, 1.5)


_DRAWERS: dict[str, Callable[[QPainter], None]] = {
    "new": _new, "open": _open, "save": _save, "undo": _undo, "redo": _redo,
    "topic": _topic, "subtopic": _subtopic, "delete": _delete, "fold": _fold,
    "zoom_in": _zoom_in, "zoom_out": _zoom_out, "fit": _fit, "theme": _theme,
    "structure": _structure, "find": _magnifier,
}


def icon_names() -> list[str]:
    return sorted(_DRAWERS)


def make_icon(name: str, color: QColor) -> QIcon:
    draw = _DRAWERS[name]
    icon = QIcon()
    for dpr in (1.0, 2.0, 3.0):
        pm = QPixmap(int(GRID * dpr), int(GRID * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        draw(p)
        p.end()
        icon.addPixmap(pm)
    return icon


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 64.0, size / 64.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2B5797"))
        p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
        p.setPen(QPen(QColor("#FFFFFF"), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        nodes = ((50, 16), (50, 48), (14, 32))
        for x, y in nodes:
            p.drawLine(QPointF(32, 32), QPointF(x, y))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(32, 32), 9, 9)
        p.setBrush(QColor("#9CD2FF"))
        for x, y in nodes:
            p.drawEllipse(QPointF(x, y), 6, 6)
        p.end()
        icon.addPixmap(pm)
    return icon
