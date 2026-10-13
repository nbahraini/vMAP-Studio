"""Tree layout engine (Qt-free).

Layouts get a ``measure(topic) -> (w, h)`` callback, keeping the engine
independent of the rendering toolkit and unit-testable.

Guarantee (tested): node boxes never overlap. Each subtree owns a disjoint
vertical band; descendants always sit beyond their parent's outer edge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from vmap.core.model import Topic

Measure = Callable[[Topic], tuple[float, float]]

# Only structures that are actually implemented are listed (spec section 66).
STRUCTURES: dict[str, str] = {
    "mind_map": "Mind Map (Balanced)",
    "logic_chart": "Logic Chart (Right)",
    "left_map": "Left Map",
}
DEFAULT_STRUCTURE = "mind_map"


@dataclass
class NodeBox:
    cx: float
    cy: float
    w: float
    h: float
    side: int  # -1 left, 0 root, +1 right

    @property
    def left(self) -> float:
        return self.cx - self.w / 2

    @property
    def right(self) -> float:
        return self.cx + self.w / 2

    @property
    def top(self) -> float:
        return self.cy - self.h / 2

    @property
    def bottom(self) -> float:
        return self.cy + self.h / 2


def visible_children(t: Topic) -> list[Topic]:
    return [] if t.folded else t.children


def compute_layout(root: Topic, measure: Measure, structure: str = DEFAULT_STRUCTURE,
                   h_gap: float = 36.0, v_gap: float = 14.0,
                   root_gap: float = 56.0) -> dict[str, NodeBox]:
    sizes: dict[str, tuple[float, float]] = {}
    heights: dict[str, float] = {}
    boxes: dict[str, NodeBox] = {}

    def size(t: Topic) -> tuple[float, float]:
        s = sizes.get(t.id)
        if s is None:
            s = sizes[t.id] = measure(t)
        return s

    def subtree_height(t: Topic) -> float:
        _, h = size(t)
        kids = visible_children(t)
        if kids:
            total = sum(subtree_height(c) for c in kids) + v_gap * (len(kids) - 1)
            h = max(h, total)
        heights[t.id] = h
        return h

    def place(kids: list[Topic], parent: NodeBox, side: int, gap: float) -> None:
        if not kids:
            return
        total = sum(heights[c.id] for c in kids) + v_gap * (len(kids) - 1)
        y = parent.cy - total / 2
        for c in kids:
            w, h = size(c)
            band = heights[c.id]
            cx = parent.right + gap + w / 2 if side > 0 else parent.left - gap - w / 2
            box = NodeBox(cx, y + band / 2, w, h, side)
            boxes[c.id] = box
            place(visible_children(c), box, side, h_gap)
            y += band + v_gap

    rw, rh = size(root)
    root_box = NodeBox(0.0, 0.0, rw, rh, 0)
    boxes[root.id] = root_box
    kids = list(root.children)          # the root itself is never folded
    for c in kids:
        subtree_height(c)
    if structure == "logic_chart":
        right, left = kids, []
    elif structure == "left_map":
        right, left = [], kids
    else:  # balanced, clockwise like classic mind-mapping tools
        split = math.ceil(len(kids) / 2)
        right, left = kids[:split], list(reversed(kids[split:]))
    place(right, root_box, +1, root_gap)
    place(left, root_box, -1, root_gap)
    return boxes
