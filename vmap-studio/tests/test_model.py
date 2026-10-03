import pytest

from vmap.core.model import (MAX_DEPTH, ROOT, TOPIC, Topic, Workbook, clone_topic, new_sheet,
                             topic_from_dict, workbook_from_dict, workbook_to_dict)


def make_tree():
    root, a, b, c = Topic("root", type=ROOT), Topic("a"), Topic("b"), Topic("c")
    root.add_child(a)
    root.add_child(b)
    a.add_child(c)
    return root, a, b, c


def test_add_remove_and_depth():
    root, a, b, c = make_tree()
    assert [t.title for t in root.children] == ["a", "b"]
    assert c.parent is a and c.depth() == 2
    assert [t.title for t in root.iter_subtree()] == ["root", "a", "c", "b"]
    assert root.remove_child(a) == 0 and a.parent is None


def test_insert_index_is_clamped():
    root, x, y = Topic(), Topic("x"), Topic("y")
    assert root.add_child(x, 99) == 0
    assert root.add_child(y, -5) == 0
    assert [t.title for t in root.children] == ["y", "x"]


def test_cycles_and_double_parents_are_rejected():
    root, a, b, c = make_tree()
    with pytest.raises(ValueError):
        c.add_child(a)          # a is an ancestor of c
    with pytest.raises(ValueError):
        a.add_child(a)
    with pytest.raises(ValueError):
        b.add_child(c)          # c still has a parent


def test_workbook_round_trip(sample_workbook):
    data = workbook_to_dict(sample_workbook)
    restored = workbook_from_dict(data)
    assert workbook_to_dict(restored) == data
    for topic in restored.sheets[0].topics():
        for child in topic.children:
            assert child.parent is topic


@pytest.mark.parametrize("bad", [
    "not a dict", {"children": "nope"}, {"position": [1]}, {"position": ["a", "b"]},
    {"z_index": True}, {"style": []}, {"labels": "x"}, {"metadata": 5}, {"metadata": []},
    {"children": {}}, {"z_index": False},
])
def test_invalid_topic_data(bad):
    with pytest.raises(ValueError):
        topic_from_dict(bad)


def test_depth_limit_guards_hostile_files():
    data = {"title": "leaf"}
    for _ in range(MAX_DEPTH + 2):
        data = {"title": "n", "children": [data]}
    with pytest.raises(ValueError):
        topic_from_dict(data)


def test_clone_has_fresh_ids_and_no_parent():
    root, a, b, c = make_tree()
    clone = clone_topic(root)
    originals = {t.id for t in root.iter_subtree()}
    copies = [t.id for t in clone.iter_subtree()]
    assert len(set(copies)) == 4 and not originals & set(copies)
    assert clone.parent is None and clone.type == TOPIC
    assert [t.title for t in clone.iter_subtree()] == ["root", "a", "c", "b"]


def test_sheet_helpers():
    sheet = new_sheet(3)
    assert sheet.title == "Sheet 3" and sheet.root.type == ROOT
    child = Topic("x")
    sheet.root.add_child(child)
    assert sheet.find(child.id) is child and sheet.count() == 2
    assert Workbook.new_default().topic_count() == 1
