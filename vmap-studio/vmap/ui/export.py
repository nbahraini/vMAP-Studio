"""Raster/vector export of the current sheet (PNG via QImage, SVG via QtSvg)."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter

from vmap import APP_NAME, __version__
from vmap.i18n import tr
from vmap.ui.canvas.scene import MapScene

EXPORT_MARGIN = 32.0
MAX_IMAGE_SIDE = 16_000


def _source(scene: MapScene) -> QRectF:
    rect = scene.content_rect()
    if rect.isNull() or rect.isEmpty():
        raise ValueError(tr("There is nothing to export."))
    return rect.adjusted(-EXPORT_MARGIN, -EXPORT_MARGIN, EXPORT_MARGIN, EXPORT_MARGIN)


def export_png(scene: MapScene, path: str | Path, scale: float = 2.0,
               transparent: bool = False) -> QSize:
    source = _source(scene)
    scale = max(0.05, min(scale, MAX_IMAGE_SIDE / max(source.width(), source.height())))
    w = max(1, math.ceil(source.width() * scale))
    h = max(1, math.ceil(source.height() * scale))
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent if transparent else scene.background_color)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                           | QPainter.RenderHint.SmoothPixmapTransform)
    try:
        with scene.exporting(transparent=transparent):
            scene.render(painter, QRectF(0, 0, w, h), source)
    finally:
        painter.end()
    if not image.save(str(path), "PNG"):
        raise OSError(tr("Could not write {path}").format(path=path))
    return QSize(w, h)


def export_svg(scene: MapScene, path: str | Path, title: str = "") -> QSize:
    from PySide6.QtSvg import QSvgGenerator

    source = _source(scene)
    w, h = math.ceil(source.width()), math.ceil(source.height())
    gen = QSvgGenerator()
    gen.setFileName(str(path))
    gen.setSize(QSize(w, h))
    gen.setViewBox(QRect(0, 0, w, h))
    gen.setResolution(96)
    gen.setTitle(title or APP_NAME)
    gen.setDescription(f"{APP_NAME} {__version__}")
    painter = QPainter()
    if not painter.begin(gen):
        raise OSError(tr("Could not write {path}").format(path=path))
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        with scene.exporting():
            scene.render(painter, QRectF(0, 0, w, h), source)
    finally:
        painter.end()
    return QSize(w, h)
