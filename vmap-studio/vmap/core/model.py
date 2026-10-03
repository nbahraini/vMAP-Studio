"""Pure-Python document model: Workbook -> Sheet -> Topic tree.

Free of Qt so the CLI, format adapters, tests and (later) AI agents and the
collaboration engine can share it. Computed layout positions are NOT stored
here; only user intent is.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from vmap.i18n import tr

ROOT = "root"
TOPIC = "topic"
MAX_DEPTH = 400  # guards recursion in loaders/layout against hostile files


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(eq=False)
class Topic:
    title: str = ""
    id: str = field(default_factory=new_id)
    type: str = TOPIC
    children: list["Topic"] = field(default_factory=list)
    parent: Optional["Topic"] = field(default=None, repr=False)
    style: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    labels: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    folded: bool = False
    position: Optional[tuple[float, float]] = None   # floating/freeform (Phase 2)
    size: Optional[tuple[float, float]] = None
    z_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)

    def touch(self) -> None:
        self.modified = now_iso()

    def index_of(self, child: "Topic") -> int:
        for i, c in enumerate(self.children):
            if c is child:
                return i
        raise ValueError("not a child of this topic")

    def add_child(self, child: "Topic", index: Optional[int] = None) -> int:
        if child is self or child.is_ancestor_of(self):
            raise ValueError(tr("A topic cannot be moved into its own subtree."))
        if child.parent is not None:
            raise ValueError("topic already has a parent; remove it first")
        if index is None or index > len(self.children):
            index = len(self.children)
        index = max(0, index)
        self.children.insert(index, child)
        child.parent = self
        self.touch()
        return index

    def remove_child(self, child: "Topic") -> int:
        index = self.index_of(child)
        del self.children[index]
        child.parent = None
        self.touch()
        return index

    def ancestors(self) -> Iterator["Topic"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def is_ancestor_of(self, other: "Topic") -> bool:
        return any(a is self for a in other.ancestors())

    def depth(self) -> int:
        return sum(1 for _ in self.ancestors())

    def iter_subtree(self) -> Iterator["Topic"]:
        """Depth-first pre-order traversal (iterative)."""
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))


@dataclass(eq=False)
class Sheet:
    title: str = "Sheet 1"
    id: str = field(default_factory=new_id)
    root: Topic = field(default_factory=lambda: Topic(title=tr("Central Topic"), type=ROOT))
    theme_id: str = "classic"
    structure: str = "mind_map"
    metadata: dict[str, Any] = field(default_factory=dict)
    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)

    def touch(self) -> None:
        self.modified = now_iso()

    def topics(self) -> Iterator[Topic]:
        return self.root.iter_subtree()

    def find(self, topic_id: str) -> Optional[Topic]:
        for t in self.topics():
            if t.id == topic_id:
                return t
        return None

    def count(self) -> int:
        return sum(1 for _ in self.topics())


@dataclass(eq=False)
class Workbook:
    sheets: list[Sheet] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)

    @classmethod
    def new_default(cls) -> "Workbook":
        return cls(sheets=[new_sheet(1)])

    def topic_count(self) -> int:
        return sum(s.count() for s in self.sheets)


def new_sheet(number: int, theme_id: str = "classic") -> Sheet:
    return Sheet(
        title=tr("Sheet {n}").format(n=number),
        root=Topic(title=tr("Central Topic"), type=ROOT),
        theme_id=theme_id,
    )


# ---------------------------------------------------------------- serialisation
def topic_to_dict(t: Topic) -> dict[str, Any]:
    d: dict[str, Any] = {"id": t.id, "type": t.type, "title": t.title,
                         "created": t.created, "modified": t.modified}
    if t.style:
        d["style"] = copy.deepcopy(t.style)
    if t.notes:
        d["notes"] = t.notes
    if t.labels:
        d["labels"] = list(t.labels)
    if t.markers:
        d["markers"] = list(t.markers)
    if t.folded:
        d["folded"] = True
    if t.position is not None:
        d["position"] = list(t.position)
    if t.size is not None:
        d["size"] = list(t.size)
    if t.z_index:
        d["z_index"] = t.z_index
    if t.metadata:
        d["metadata"] = copy.deepcopy(t.metadata)
    if t.children:
        d["children"] = [topic_to_dict(c) for c in t.children]
    return d


def _field(d: dict, key: str, kind: type) -> Any:
    """Missing/None -> empty default; a present value must have exactly this type."""
    value = d.get(key)
    if value is None:
        return kind()
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ValueError(f"{key} must be of type {kind.__name__}")
    return value


def _pair(value: Any) -> Optional[tuple[float, float]]:
    if value is None:
        return None
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value)):
        return float(value[0]), float(value[1])
    raise ValueError(f"invalid coordinate pair: {value!r}")


def _str_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return [str(x) for x in value]


def topic_from_dict(d: Any, parent: Optional[Topic] = None, _depth: int = 0) -> Topic:
    if not isinstance(d, dict):
        raise ValueError("topic must be an object")
    if _depth > MAX_DEPTH:
        raise ValueError(f"topic tree deeper than {MAX_DEPTH} levels")
    style = _field(d, "style", dict)
    metadata = _field(d, "metadata", dict)
    if not isinstance(style, dict) or not isinstance(metadata, dict):
        raise ValueError("style and metadata must be objects")
    children = _field(d, "children", list)
    if not isinstance(children, list):
        raise ValueError("children must be a list")
    z = _field(d, "z_index", int)
    if not isinstance(z, int) or isinstance(z, bool):
        raise ValueError("z_index must be an integer")
    t = Topic(
        title=str(d.get("title", "")),
        id=str(d.get("id") or new_id()),
        type=str(d.get("type") or TOPIC),
        style=dict(style),
        notes=str(d.get("notes") or ""),
        labels=_str_list(d.get("labels"), "labels"),
        markers=_str_list(d.get("markers"), "markers"),
        folded=bool(d.get("folded", False)),
        position=_pair(d.get("position")),
        size=_pair(d.get("size")),
        z_index=z,
        metadata=dict(metadata),
        created=str(d.get("created") or now_iso()),
        modified=str(d.get("modified") or now_iso()),
    )
    t.parent = parent
    t.children = [topic_from_dict(c, t, _depth + 1) for c in children]
    return t


def sheet_to_dict(s: Sheet) -> dict[str, Any]:
    d = {"id": s.id, "title": s.title, "theme_id": s.theme_id, "structure": s.structure,
         "created": s.created, "modified": s.modified, "root": topic_to_dict(s.root)}
    if s.metadata:
        d["metadata"] = copy.deepcopy(s.metadata)
    return d


def sheet_from_dict(d: Any) -> Sheet:
    if not isinstance(d, dict) or "root" not in d:
        raise ValueError("sheet must be an object with a root topic")
    metadata = _field(d, "metadata", dict)
    if not isinstance(metadata, dict):
        raise ValueError("sheet metadata must be an object")
    return Sheet(
        title=str(d.get("title") or "Sheet"),
        id=str(d.get("id") or new_id()),
        root=topic_from_dict(d["root"]),
        theme_id=str(d.get("theme_id") or "classic"),
        structure=str(d.get("structure") or "mind_map"),
        metadata=dict(metadata),
        created=str(d.get("created") or now_iso()),
        modified=str(d.get("modified") or now_iso()),
    )


def workbook_to_dict(wb: Workbook) -> dict[str, Any]:
    d = {"id": wb.id, "title": wb.title, "created": wb.created, "modified": wb.modified,
         "sheets": [sheet_to_dict(s) for s in wb.sheets]}
    if wb.metadata:
        d["metadata"] = copy.deepcopy(wb.metadata)
    return d


def workbook_from_dict(d: Any) -> Workbook:
    if not isinstance(d, dict):
        raise ValueError("workbook must be an object")
    sheets = d.get("sheets")
    if not isinstance(sheets, list):
        raise ValueError("workbook.sheets must be a list")
    metadata = _field(d, "metadata", dict)
    if not isinstance(metadata, dict):
        raise ValueError("workbook metadata must be an object")
    return Workbook(
        sheets=[sheet_from_dict(s) for s in sheets],
        id=str(d.get("id") or new_id()),
        title=str(d.get("title") or ""),
        metadata=dict(metadata),
        created=str(d.get("created") or now_iso()),
        modified=str(d.get("modified") or now_iso()),
    )


def clone_topic(t: Topic) -> Topic:
    """Deep copy of a subtree with fresh UUIDs (copy/paste, duplicate)."""
    data = topic_to_dict(t)
    stamp = now_iso()
    stack = [data]
    while stack:
        node = stack.pop()
        node["id"] = new_id()
        node["created"] = node["modified"] = stamp
        stack.extend(node.get("children", []))
    clone = topic_from_dict(data)
    clone.type = TOPIC
    return clone
