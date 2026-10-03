"""Run blocking work (file I/O, parsing) off the UI thread.

The worker is a plain Python thread; the UI thread spins a local event loop
that keeps repainting but ignores user input until the work completes, so the
document cannot be mutated while it is being read or written.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, TypeVar

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QProgressDialog, QWidget

T = TypeVar("T")
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vmap-io")


def run_in_background(parent: Optional[QWidget], label: str, fn: Callable[[], T]) -> T:
    """Run fn() in a worker thread; return its result or re-raise its exception."""
    future = _executor.submit(fn)
    if not future.done():
        dialog = QProgressDialog(label, "", 0, 0, parent)
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(400)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(15)
        timer.timeout.connect(lambda: loop.quit() if future.done() else None)
        timer.start()
        if not future.done():
            loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        timer.stop()
        dialog.close()
        dialog.deleteLater()
    return future.result()
