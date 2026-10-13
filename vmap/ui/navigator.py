"""Overview navigator: a cached thumbnail of the map plus the visible area.

The thumbnail is re-rendered only after the map changes (debounced), so
scrolling the main canvas just repaints a pixmap and a rectangle.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from vmap.i18n import tr
from vmap.ui.canvas.items import SELECTION_COLOR
from vmap.ui.canvas.view import MapView


class NavigatorWidget(QWidget):
    def __init__(self, view: MapView, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        self._pixmap = QPixmap()
        self._source = QRectF()
        self._target = QRectF()
        self._scale = 1.0
        self._dragging = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.render_thumbnail)
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Click or drag to move the visible area"))
        view.map_rendered.connect(self._timer.start)
        view.viewport_changed.connect(self.update)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def render_thumbnail(self) -> None:
        if not self.isVisible():
            return
        scene = self.view.scene_
        content = scene.content_rect()
        if content.isEmpty() or self.width() < 20 or self.height() < 20:
            self._pixmap = QPixmap()
            self.update()
            return
        source = content.adjusted(-24, -24, 24, 24)
        s = min((self.width() - 8) / source.width(), (self.height() - 8) / source.height(), 1.0)
        tw, th = source.width() * s, source.height() * s
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, math.ceil(tw * dpr)), max(1, math.ceil(th * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(scene.background_color)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            with scene.exporting():
                scene.render(painter, QRectF(0, 0, tw, th), source)
        finally:
            painter.end()
        self._pixmap, self._source, self._scale = pm, source, s
        self._target = QRectF((self.width() - tw) / 2, (self.height() - th) / 2, tw, th)
        self.update()

    def _to_widget(self, r: QRectF) -> QRectF:
        s, src, tgt = self._scale, self._source, self._target
        return QRectF(tgt.left() + (r.left() - src.left()) * s,
                      tgt.top() + (r.top() - src.top()) * s, r.width() * s, r.height() * s)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        if self._pixmap.isNull():
            p.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Empty map"))
            return
        p.drawPixmap(self._target.topLeft(), self._pixmap)
        visible = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        r = self._to_widget(visible).intersected(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        if r.isEmpty():
            return
        fill = QColor(SELECTION_COLOR)
        fill.setAlpha(30)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(SELECTION_COLOR, 1.5))
        p.setBrush(fill)
        p.drawRect(r)

    def _move_to(self, pos: QPointF) -> None:
        s, src, tgt = self._scale, self._source, self._target
        self.view.centerOn(QPointF(src.left() + (pos.x() - tgt.left()) / s,
                                   src.top() + (pos.y() - tgt.top()) / s))
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._pixmap.isNull():
            self._dragging = True
            self._move_to(event.position())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._move_to(event.position())

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
