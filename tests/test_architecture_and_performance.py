import subprocess
import sys
import textwrap
import time
from pathlib import Path

from vmap.core.model import ROOT, Topic, Workbook, workbook_from_dict, workbook_to_dict
from vmap.mindmap.layouts import compute_layout

PROJECT = Path(__file__).resolve().parents[1]


def test_core_never_imports_qt():
    """The engine must stay usable without PySide6 (CLI, servers, AI agents)."""
    code = textwrap.dedent("""
        import sys
        sys.modules["PySide6"] = None   # any Qt import now fails
        import vmap.core.model, vmap.core.commands, vmap.core.document, vmap.core.search
        import vmap.core.validation, vmap.core.outline, vmap.core.markers, vmap.mindmap.layouts
        import vmap.themes.engine, vmap.formats, vmap.cli.main
        assert vmap.cli.main.main(["theme", "list"]) == 0
    """)
    result = subprocess.run([sys.executable, "-c", code], cwd=PROJECT, capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr


def _big_tree() -> Topic:
    root = Topic("root", type=ROOT)
    for i in range(10):
        a = Topic(f"{i}")
        root.add_child(a)
        for j in range(10):
            b = Topic(f"{i}.{j}")
            a.add_child(b)
            for k in range(99):
                b.add_child(Topic(f"{i}.{j}.{k}"))
    return root


def test_layout_10k_topics_is_fast():
    root = _big_tree()
    start = time.perf_counter()
    boxes = compute_layout(root, lambda t: (80.0, 24.0))
    elapsed = time.perf_counter() - start
    assert len(boxes) == 10_011
    assert elapsed < 5.0, f"layout took {elapsed:.2f}s"


def test_serialisation_10k_topics_is_fast():
    wb = Workbook.new_default()
    wb.sheets[0].root = _big_tree()
    start = time.perf_counter()
    restored = workbook_from_dict(workbook_to_dict(wb))
    elapsed = time.perf_counter() - start
    assert restored.topic_count() == 10_011
    assert elapsed < 5.0, f"round trip took {elapsed:.2f}s"
