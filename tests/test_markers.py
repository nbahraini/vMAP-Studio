"""Markers (core rules, command, UI) and the note workflow (F4 popup, note icon, balloon)."""
import pytest

from vmap.core.commands import SetMarkersCommand, SetTopicAttrCommand, UndoStack
from vmap.core.markers import (GROUPS, MAX_MARKERS_PER_TOPIC, apply_marker, display_markers,
                               group_of, is_custom, marker_name, sort_markers)
from vmap.core.model import Topic, Workbook

ALL_IDS = [m for _, _, ids in GROUPS for m in ids]
CUSTOM_A, CUSTOM_B = "custom:" + "a" * 16, "custom:" + "b" * 16


# ------------------------------------------------------------------- core
def test_catalogue_complete_and_named():
    assert len(ALL_IDS) == len(set(ALL_IDS)) == 88
    assert [g for g, _, _ in GROUPS] == ["priority", "smiley", "task", "flag", "star", "people",
                                         "arrow", "symbol", "traffic", "month", "week"]
    assert all(marker_name(m) != m for m in ALL_IDS)


def test_exclusive_groups_toggle_and_order():
    ids = apply_marker([], "priority-1")
    assert ids == ["priority-1"]
    assert apply_marker(ids, "priority-3") == ["priority-3"]
    assert apply_marker(["priority-3"], "priority-3") == []
    assert apply_marker(["flag-red"], "priority-2") == ["priority-2", "flag-red"]
    both = apply_marker(["symbol-info"], "symbol-plus")
    assert both == ["symbol-plus", "symbol-info"]            # symbols are not exclusive
    assert apply_marker(both, "symbol-plus", "add") == both
    assert apply_marker(both, "symbol-plus", "remove") == ["symbol-info"]
    with pytest.raises(ValueError):
        apply_marker([], "flag-red", "bogus")


def test_sort_and_custom_ids():
    assert sort_markers(["zzz", CUSTOM_A, "flag-red", "priority-1", "flag-red", 5]) == [
        "priority-1", "flag-red", CUSTOM_A, "zzz"]
    assert is_custom(CUSTOM_A) and group_of(CUSTOM_A) == "custom"
    assert not is_custom("custom:../../etc/passwd") and group_of("nope") is None
    assert apply_marker([CUSTOM_A], CUSTOM_B) == [CUSTOM_A, CUSTOM_B]
    many = [f"x{i}" for i in range(MAX_MARKERS_PER_TOPIC + 5)]
    assert len(display_markers(many)) == MAX_MARKERS_PER_TOPIC
    with pytest.raises(ValueError):
        apply_marker(many[:MAX_MARKERS_PER_TOPIC], "flag-red")


def test_set_markers_command_is_one_undo_step():
    a, b = Topic("a"), Topic("b", markers=["flag-red"])
    stack = UndoStack()
    stack.push(SetMarkersCommand([(a, ["priority-1"]), (b, [])]))
    assert a.markers == ["priority-1"] and b.markers == []
    stack.undo()
    assert a.markers == [] and b.markers == ["flag-red"]
    with pytest.raises(ValueError):
        SetMarkersCommand([(a, ["x"] * (MAX_MARKERS_PER_TOPIC + 1))])


# --------------------------------------------------------------------- UI
@pytest.fixture
def window(qapp, tmp_path):
    from vmap.ui.context import AppContext
    from vmap.ui.mainwindow import MainWindow
    ctx = AppContext.create(tmp_path / "data")
    win = MainWindow(ctx)
    win.show()
    qapp.processEvents()
    yield win
    win.note_popup.hide()
    win.view.finish_edit(commit=False)
    win.document.undo_stack.set_clean()
    win.close()
    qapp.processEvents()
    win.deleteLater()
    qapp.processEvents()
    ctx.db.close()


def test_every_builtin_marker_has_artwork(qapp):
    from vmap.ui.markers import _PAINTERS
    assert set(_PAINTERS) == set(ALL_IDS)


def test_note_summary(qapp):
    from vmap.ui.notes import note_summary
    assert note_summary("a\n\n\n b   c ") == ("a\n\nb c", False)
    text, truncated = note_summary("\n".join(str(i) for i in range(30)))
    assert truncated and text.count("\n") == 11


def test_toggle_markers_render_and_undo(window):
    view, root = window.view, window.view.sheet.root
    view.select_topics([root])
    width_before = view.scene_.item_for(root).w
    window.markers.toggle("priority-1")
    window.markers.toggle("flag-red")
    window.a_priority[2].trigger()                            # Ctrl+3
    assert root.markers == ["priority-3", "flag-red"]
    item = view.scene_.item_for(root)
    assert item.w > width_before
    assert [m for m, _ in item.marker_rects()] == ["priority-3", "flag-red"]
    centre = item.mapRectToScene(item.marker_rects()[1][1]).center()
    assert item.marker_at(centre) == "flag-red"
    window.document.undo()
    assert root.markers == ["priority-1", "flag-red"]
    window.markers.clear()
    assert root.markers == []


def test_f4_opens_note_editor_and_commits(window):
    view, root = window.view, window.view.sheet.root
    assert window.a_note.shortcut().toString() == "F4"
    view.select_topics([root])
    window.a_note.trigger()
    popup = window.note_popup
    assert popup.isVisible() and popup.topic is root
    popup.editor.setPlainText("first line\nsecond line")
    popup.close()
    assert root.notes == "first line\nsecond line"
    assert view.scene_.item_for(root).note_icon_rect() is not None
    window.document.undo()
    assert root.notes == ""


def test_note_icon_click_opens_editor(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    view, root = window.view, window.view.sheet.root
    window.document.execute(SetTopicAttrCommand(root, "notes", "hello"), view.sheet)
    item = view.scene_.item_for(root)
    centre = item.mapRectToScene(item.note_icon_rect()).center()
    assert item.note_icon_hit(centre) and not item.note_icon_hit(item.scenePos())
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     view.mapFromScene(centre))
    QTest.qWait(50)
    assert window.note_popup.isVisible() and window.note_popup.topic is root


def test_custom_markers_library_and_embedding(qapp, tmp_path):
    from PySide6.QtGui import QColor, QImage
    from vmap.ui.markers import EMBED_KEY, MarkerLibrary, embed_custom_markers
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor("#FF0000"))
    png = tmp_path / "vpn.png"
    assert image.save(str(png), "PNG")
    fake = tmp_path / "fake.svg"
    fake.write_text("not an image", encoding="utf-8")
    library = MarkerLibrary(tmp_path / "markers")
    added, errors = library.add_files([png, fake], "Network")
    assert len(added) == 1 and is_custom(added[0]) and len(errors) == 1
    reloaded = MarkerLibrary(tmp_path / "markers")
    assert reloaded.load() == [] and reloaded.name(added[0]) == "vpn"
    wb = Workbook.new_default()
    wb.sheets[0].root.markers = [added[0], "flag-red"]
    embed_custom_markers(wb, library)
    embedded = wb.metadata[EMBED_KEY]
    other = MarkerLibrary(None)
    assert other.import_embedded(embedded) == [] and other.has(added[0])
    tampered = [dict(embedded[0], id=CUSTOM_B)]
    assert MarkerLibrary(None).import_embedded(tampered)          # rejected with a warning
    wb.sheets[0].root.markers = []
    embed_custom_markers(wb, library)
    assert EMBED_KEY not in wb.metadata
