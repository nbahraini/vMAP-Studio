import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # headless Qt for CI

import pytest

from vmap.core.model import Topic, Workbook


@pytest.fixture
def sample_workbook() -> Workbook:
    """Root + 3 branches + 6 leaves = 10 topics, with notes/style/fold/labels."""
    wb = Workbook.new_default()
    root = wb.sheets[0].root
    for i in range(3):
        branch = Topic(title=f"Branch {i}")
        root.add_child(branch)
        for j in range(2):
            branch.add_child(Topic(title=f"Leaf {i}.{j}"))
    root.children[0].notes = "Some notes\nwith two lines"
    root.children[0].labels = ["security"]
    root.children[0].markers = ["priority-1"]
    root.children[1].style = {"fill": "#FF0000", "bold": True}
    root.children[2].folded = True
    root.children[2].metadata = {"source": "test"}
    return wb


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
