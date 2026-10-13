import pytest

from vmap.core.commands import (AddSheetCommand, AddTopicCommand, DeleteTopicCommand,
                                MacroCommand, MoveTopicCommand, RemoveSheetCommand,
                                SetSheetAttrCommand, SetStyleCommand, SetTopicAttrCommand,
                                SortChildrenCommand, UndoStack)
from vmap.core.document import Document
from vmap.core.model import ROOT, Topic, Workbook, new_sheet


def titles(topic):
    return [t.title for t in topic.children]


def tree():
    root = Topic("root", type=ROOT)
    for name in ("a", "b", "c"):
        root.add_child(Topic(name))
    return root


def test_add_delete_undo_redo():
    stack, root, x = UndoStack(), tree(), Topic("x")
    stack.push(AddTopicCommand(root, x, 1))
    assert titles(root) == ["a", "x", "b", "c"]
    stack.push(DeleteTopicCommand(root.children[0]))
    assert titles(root) == ["x", "b", "c"]
    stack.undo()
    stack.undo()
    assert titles(root) == ["a", "b", "c"]
    stack.redo()
    stack.redo()
    assert titles(root) == ["x", "b", "c"]


def test_root_cannot_be_deleted_or_moved():
    root = tree()
    with pytest.raises(ValueError):
        DeleteTopicCommand(root)
    with pytest.raises(ValueError):
        MoveTopicCommand(root, root.children[0])


def test_move_reorder_and_reparent():
    root = tree()
    a, b, c = root.children
    stack = UndoStack()
    stack.push(MoveTopicCommand(a, root, 2))
    assert titles(root) == ["b", "c", "a"]
    stack.push(MoveTopicCommand(c, b))
    assert c.parent is b and titles(root) == ["b", "a"]
    with pytest.raises(ValueError):
        MoveTopicCommand(b, c)          # into own subtree
    stack.undo()
    stack.undo()
    assert titles(root) == ["a", "b", "c"]


def test_set_attr_and_style_restore_exactly():
    root = tree()
    a, b, _ = root.children
    a.style = {"fill": "#111111"}
    stack = UndoStack()
    stack.push(SetTopicAttrCommand([a, b], "title", "same"))
    stack.push(SetStyleCommand([a, b], {"fill": "#222222", "bold": True}))
    assert a.style == b.style == {"fill": "#222222", "bold": True}
    stack.push(SetStyleCommand([a], {"fill": None}))
    assert "fill" not in a.style
    stack.undo()
    stack.undo()
    assert a.style == {"fill": "#111111"} and b.style == {}
    stack.undo()
    assert (a.title, b.title) == ("a", "b")
    with pytest.raises(ValueError):
        SetTopicAttrCommand(a, "id", "hacked")


def test_sort_children():
    root = Topic("root", type=ROOT)
    for name in ("b", "A", "c"):
        root.add_child(Topic(name))
    stack = UndoStack()
    stack.push(SortChildrenCommand(root))
    assert titles(root) == ["A", "b", "c"]
    stack.push(SortChildrenCommand(root, reverse=True))
    assert titles(root) == ["c", "b", "A"]
    stack.undo()
    stack.undo()
    assert titles(root) == ["b", "A", "c"]


def test_macro_is_atomic_and_rolls_back():
    root = tree()
    orphan_with_parent = root.children[0]
    stack = UndoStack()
    new = Topic("new")
    macro = MacroCommand("bad", [AddTopicCommand(root, new), AddTopicCommand(root, orphan_with_parent)])
    with pytest.raises(ValueError):
        stack.push(macro)
    assert titles(root) == ["a", "b", "c"] and not stack.can_undo

    stack.push(MacroCommand("two", [AddTopicCommand(root, Topic("x")), AddTopicCommand(root, Topic("y"))]))
    assert titles(root)[-2:] == ["x", "y"] and stack.undo_label == "two"
    stack.undo()
    assert titles(root) == ["a", "b", "c"]


def test_clean_state_tracking():
    root, stack = tree(), UndoStack()
    assert stack.is_clean
    stack.push(AddTopicCommand(root, Topic("1")))
    stack.set_clean()
    stack.push(AddTopicCommand(root, Topic("2")))
    assert not stack.is_clean
    stack.undo()
    assert stack.is_clean
    stack.undo()
    assert not stack.is_clean
    stack.redo()
    assert stack.is_clean
    stack.undo()
    stack.push(AddTopicCommand(root, Topic("3")))   # clean state no longer reachable
    assert not stack.is_clean
    stack.undo()
    assert not stack.is_clean


def test_limit_trims_oldest():
    root, stack = tree(), UndoStack(limit=2)
    for i in range(3):
        stack.push(AddTopicCommand(root, Topic(str(i))))
    assert stack.count() == 2 and not stack.is_clean
    stack.undo()
    stack.undo()
    assert stack.undo() is None and titles(root)[-1] == "0"


def test_sheet_commands():
    wb = Workbook.new_default()
    first = wb.sheets[0]
    stack = UndoStack()
    second = new_sheet(2)
    stack.push(AddSheetCommand(wb, second, 0))
    assert wb.sheets == [second, first]
    stack.push(SetSheetAttrCommand(second, "structure", "logic_chart"))
    stack.push(RemoveSheetCommand(wb, second))
    assert wb.sheets == [first]
    with pytest.raises(ValueError):
        RemoveSheetCommand(wb, first)
    with pytest.raises(ValueError):
        SetSheetAttrCommand(first, "id", "x")
    stack.undo()
    assert wb.sheets == [second, first] and second.structure == "logic_chart"
    stack.undo()
    assert second.structure == "mind_map"


def test_document_events_and_saved_state(tmp_path):
    doc = Document()
    seen = []
    doc.events.subscribe("changed", lambda command: seen.append(command))
    root = doc.workbook.sheets[0].root
    cmd = AddTopicCommand(root, Topic("x"))
    doc.execute(cmd, doc.workbook.sheets[0])
    assert seen == [cmd] and cmd.sheet is doc.workbook.sheets[0]
    assert doc.is_modified and doc.display_name == "Untitled"
    doc.mark_saved(tmp_path / "a.vmap")
    assert not doc.is_modified and doc.display_name == "a.vmap"
    doc.undo()
    assert doc.is_modified and seen[-1] is cmd
