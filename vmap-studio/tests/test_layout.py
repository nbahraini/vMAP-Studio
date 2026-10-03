import math
import random

import pytest

from vmap.core.model import ROOT, Topic
from vmap.mindmap.layouts import STRUCTURES, compute_layout


def random_tree(seed: int, n: int = 250):
    rng = random.Random(seed)
    root = Topic("root", type=ROOT)
    nodes, sizes = [root], {root.id: (120.0, 40.0)}
    for i in range(n):
        child = Topic(f"t{i}")
        rng.choice(nodes).add_child(child)
        nodes.append(child)
        sizes[child.id] = (rng.uniform(30, 220), rng.uniform(18, 90))
    return root, sizes


def overlaps(a, b, eps=1e-6) -> bool:
    return (a.left < b.right - eps and b.left < a.right - eps
            and a.top < b.bottom - eps and b.top < a.bottom - eps)


@pytest.mark.parametrize("structure", list(STRUCTURES))
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_boxes_never_overlap(structure, seed):
    root, sizes = random_tree(seed)
    boxes = compute_layout(root, lambda t: sizes[t.id], structure)
    assert len(boxes) == len(sizes)
    items = list(boxes.values())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            assert not overlaps(items[i], items[j])


def test_sides_per_structure():
    root = Topic("root", type=ROOT)
    for i in range(5):
        root.add_child(Topic(str(i)))
    measure = lambda t: (60.0, 20.0)
    right = compute_layout(root, measure, "logic_chart")
    left = compute_layout(root, measure, "left_map")
    balanced = compute_layout(root, measure, "mind_map")
    kids = root.children
    assert all(right[k.id].side == 1 and right[k.id].left > right[root.id].right for k in kids)
    assert all(left[k.id].side == -1 and left[k.id].right < left[root.id].left for k in kids)
    split = math.ceil(len(kids) / 2)
    assert [balanced[k.id].side for k in kids] == [1] * split + [-1] * (len(kids) - split)
    assert (right[root.id].cx, right[root.id].cy) == (0.0, 0.0)
    ys = [right[k.id].cy for k in kids]
    assert ys == sorted(ys)


def test_folded_branches_are_hidden():
    root, a, b = Topic("root", type=ROOT), Topic("a"), Topic("b")
    root.add_child(a)
    a.add_child(b)
    a.folded = True
    boxes = compute_layout(root, lambda t: (50.0, 20.0))
    assert a.id in boxes and b.id not in boxes
