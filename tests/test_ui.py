"""Headless GUI tests (QT_QPA_PLATFORM=offscreen is set in conftest.py)."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from vmap.core.commands import AddTopicCommand
from vmap.core.model import Topic


@pytest.fixture
def window(qapp, tmp_path):
    from vmap.ui.context import AppContext
    from vmap.ui.mainwindow import MainWindow
    ctx = AppContext.create(tmp_path / "data")
    win = MainWindow(ctx)
    win.show()
    qapp.processEvents()
    yield win
    win.view.finish_edit(commit=False)
    win.document.undo_stack.set_clean()   # never block teardown on a save prompt
    win.close()
    qapp.processEvents()
    win.deleteLater()
    qapp.processEvents()
    ctx.db.close()


def add(window, parent, title):
    topic = Topic(title)
    window.document.execute(AddTopicCommand(parent, topic), window.view.sheet)
    return topic


def test_starts_with_selected_root(window):
    sheet = window.view.sheet
    assert sheet.root.title == "Central Topic"
    assert window.view.current_topic() is sheet.root
    assert len(window.view.scene_.topic_items()) == 1 and window.tabs.count() == 1
    assert not window.document.is_modified


def test_tab_creates_subtopic_and_inline_edit(window):
    view, root = window.view, window.view.sheet.root
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Tab)
    assert len(root.children) == 1 and view.is_editing
    QTest.keyClicks(view._editor, "Hello")
    QTest.keyClick(view._editor, Qt.Key.Key_Return)
    assert not view.is_editing and root.children[0].title == "Hello"
    assert window.document.is_modified and window.isWindowModified()
    window.document.undo()
    assert root.children[0].title == "Main Topic 1"
    window.document.undo()
    assert root.children == []


def test_typing_starts_editing(window):
    view, root = window.view, window.view.sheet.root
    view.setFocus()
    QTest.keyClicks(view, "x")
    assert view.is_editing
    QTest.keyClick(view._editor, Qt.Key.Key_Return)
    assert root.title == "x"


def test_enter_adds_sibling_and_delete_selects_neighbour(window):
    view, root = window.view, window.view.sheet.root
    a = add(window, root, "A")
    view.select_topics([a])
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Return)
    view.finish_edit(commit=False)
    assert len(root.children) == 2 and root.children[0] is a
    view.select_topics([root.children[1]])
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert root.children == [a] and view.current_topic() is a


def test_fold_drop_move_and_parent(window):
    view, ops, root = window.view, window.view.ops, window.view.sheet.root
    a, b = add(window, root, "A"), add(window, root, "B")
    c = add(window, a, "C")
    ops.set_folded([a], True)
    assert view.scene_.item_for(c) is None
    window.document.undo()
    assert view.scene_.item_for(c) is not None
    ops.drop_topic(c, b, "child")
    assert c.parent is b
    ops.drop_topic(c, a, "before")
    assert root.children[0] is c
    view.select_topics([c])
    ops.move_sibling(1)
    assert root.children[1] is c
    view.select_topics([a])
    ops.add_parent()
    view.finish_edit(commit=False)
    assert a.parent.parent is root and a.parent.children == [a]


def test_inspector_style_and_theme(window):
    root = window.view.sheet.root
    a = add(window, root, "A")
    window.view.select_topics([a])
    window.inspector._set_style("fill", "#FF0000")
    assert a.style["fill"] == "#FF0000"
    assert window.view.scene_.style_for(a)["fill"] == "#FF0000"
    window.document.undo()
    assert "fill" not in a.style
    window._set_sheet_attr("theme_id", "dark", "Change Theme")
    assert window.view.scene_.background_color == QColor("#1E1F24")
    window.document.undo()
    assert window.view.sheet.theme_id == "classic"


def test_sheets_add_duplicate_undo(window):
    first = window.view.sheet
    window._new_sheet()
    sheets = window.document.workbook.sheets
    assert len(sheets) == 2 and window.view.sheet is sheets[1] and window.tabs.count() == 2
    window._duplicate_sheet(0)
    assert len(sheets) == 3 and sheets[1].root is not first.root
    window.document.undo()
    window.document.undo()
    assert len(sheets) == 1 and window.view.sheet is first and window.tabs.count() == 1


def test_find_and_replace_all(window):
    root = window.view.sheet.root
    a, b = add(window, root, "alpha one"), add(window, root, "beta")
    c = add(window, b, "alpha two")
    bar = window.findbar
    bar.find_edit.setText("alpha")
    bar.find_next()
    assert window.view.current_topic() is a
    bar.find_next()
    assert window.view.current_topic() is c
    bar.replace_edit.setText("gamma")
    bar.replace_all()
    assert (a.title, c.title) == ("gamma one", "gamma two")
    window.document.undo()                       # one undo step for Replace All
    assert (a.title, c.title) == ("alpha one", "alpha two")


def test_save_and_reopen(window, tmp_path):
    from vmap.ui.mainwindow import MainWindow
    add(window, window.view.sheet.root, "Saved topic")
    path = tmp_path / "saved.vmap"
    assert window._save_to(path)
    assert not window.document.is_modified and window.document.path == path
    other = MainWindow(window.ctx)
    other.open_path(path)
    assert other.document.path == path
    assert other.document.workbook.sheets[0].root.children[0].title == "Saved topic"
    other.close()
    other.deleteLater()


def test_export_png_svg_and_navigator(window, tmp_path, qapp):
    from vmap.ui.export import export_png, export_svg
    add(window, window.view.sheet.root, "Export me")
    size = export_png(window.view.scene_, tmp_path / "m.png", scale=1.0)
    assert size.width() > 0 and (tmp_path / "m.png").read_bytes()[:4] == b"\x89PNG"
    export_svg(window.view.scene_, tmp_path / "m.svg")
    assert "<svg" in (tmp_path / "m.svg").read_text(encoding="utf-8")
    qapp.processEvents()
    window.navigator.render_thumbnail()
    assert not window.navigator._pixmap.isNull()
