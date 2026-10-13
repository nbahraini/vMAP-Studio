"""Command pattern + undo stack (Qt-free).

Every model mutation is a Command, so every operation is undoable. Composite
operations (paste, multi-delete, future AI edits) use MacroCommand and undo as
ONE transaction.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Iterable, Optional, Union

from vmap.core.markers import MAX_MARKERS_PER_TOPIC
from vmap.core.model import Sheet, Topic, Workbook
from vmap.i18n import tr

_MISSING = object()
TopicsArg = Union[Topic, Iterable[Topic]]


def _as_list(topics: TopicsArg) -> list[Topic]:
    return [topics] if isinstance(topics, Topic) else list(topics)


class Command(ABC):
    label: str = "Edit"

    def __init__(self) -> None:
        self.sheet: Optional[Sheet] = None   # sheet the UI should show afterwards

    @abstractmethod
    def redo(self) -> None: ...

    @abstractmethod
    def undo(self) -> None: ...


class MacroCommand(Command):
    def __init__(self, label: str, commands: Iterable[Command]) -> None:
        super().__init__()
        self.label = label
        self.commands = list(commands)

    def redo(self) -> None:
        done: list[Command] = []
        try:
            for c in self.commands:
                c.redo()
                done.append(c)
        except Exception:
            for c in reversed(done):
                c.undo()
            raise

    def undo(self) -> None:
        for c in reversed(self.commands):
            c.undo()


class AddTopicCommand(Command):
    def __init__(self, parent: Topic, topic: Topic, index: Optional[int] = None,
                 label: Optional[str] = None) -> None:
        super().__init__()
        self.parent, self.topic, self.index = parent, topic, index
        self.label = label or tr("Add Topic")

    def redo(self) -> None:
        self.index = self.parent.add_child(self.topic, self.index)

    def undo(self) -> None:
        self.parent.remove_child(self.topic)


class DeleteTopicCommand(Command):
    def __init__(self, topic: Topic) -> None:
        super().__init__()
        if topic.parent is None:
            raise ValueError(tr("The root topic cannot be deleted."))
        self.topic, self.parent, self.index = topic, topic.parent, -1
        self.label = tr("Delete Topic")

    def redo(self) -> None:
        self.index = self.parent.remove_child(self.topic)

    def undo(self) -> None:
        self.parent.add_child(self.topic, self.index)


class MoveTopicCommand(Command):
    """Re-parent and/or reorder. new_index is the index in the final list."""

    def __init__(self, topic: Topic, new_parent: Topic, new_index: Optional[int] = None,
                 label: Optional[str] = None) -> None:
        super().__init__()
        if topic.parent is None:
            raise ValueError(tr("The root topic cannot be moved."))
        if new_parent is topic or topic.is_ancestor_of(new_parent):
            raise ValueError(tr("A topic cannot be moved into its own subtree."))
        self.topic, self.new_parent, self.new_index = topic, new_parent, new_index
        self.old_parent = topic.parent
        self.old_index = topic.parent.index_of(topic)
        self.label = label or tr("Move Topic")

    def redo(self) -> None:
        self.old_parent.remove_child(self.topic)
        self.new_index = self.new_parent.add_child(self.topic, self.new_index)

    def undo(self) -> None:
        self.new_parent.remove_child(self.topic)
        self.old_parent.add_child(self.topic, self.old_index)


EDITABLE_TOPIC_ATTRS = frozenset({"title", "notes", "folded"})


class SetTopicAttrCommand(Command):
    def __init__(self, topics: TopicsArg, attr: str, value: Any,
                 label: Optional[str] = None) -> None:
        super().__init__()
        if attr not in EDITABLE_TOPIC_ATTRS:
            raise ValueError(f"topic attribute {attr!r} is not editable")
        self.topics = _as_list(topics)
        self.attr, self.value = attr, value
        self.old = [getattr(t, attr) for t in self.topics]
        self.label = label or tr("Edit Topic")

    def redo(self) -> None:
        for t in self.topics:
            setattr(t, self.attr, self.value)
            t.touch()

    def undo(self) -> None:
        for t, v in zip(self.topics, self.old):
            setattr(t, self.attr, v)
            t.touch()


class SetStyleCommand(Command):
    """values: {style_key: value}; a value of None removes the override."""

    def __init__(self, topics: TopicsArg, values: dict[str, Any],
                 label: Optional[str] = None) -> None:
        super().__init__()
        self.topics = _as_list(topics)
        self.values = dict(values)
        self.old = [{k: t.style.get(k, _MISSING) for k in self.values} for t in self.topics]
        self.label = label or tr("Change Style")

    def redo(self) -> None:
        for t in self.topics:
            for k, v in self.values.items():
                if v is None:
                    t.style.pop(k, None)
                else:
                    t.style[k] = v
            t.touch()

    def undo(self) -> None:
        for t, old in zip(self.topics, self.old):
            for k, v in old.items():
                if v is _MISSING:
                    t.style.pop(k, None)
                else:
                    t.style[k] = v
            t.touch()


class SetMarkersCommand(Command):
    """Replace the marker lists of one or more topics as one undo step."""

    def __init__(self, changes: Iterable[tuple[Topic, list[str]]],
                 label: Optional[str] = None) -> None:
        super().__init__()
        self.changes = [(t, list(t.markers), [str(m) for m in new]) for t, new in changes]
        if any(len(new) > MAX_MARKERS_PER_TOPIC for _, _, new in self.changes):
            raise ValueError(tr("A topic can carry at most {n} markers.").format(
                n=MAX_MARKERS_PER_TOPIC))
        self.label = label or tr("Change Markers")

    def redo(self) -> None:
        for t, _, new in self.changes:
            t.markers = list(new)
            t.touch()

    def undo(self) -> None:
        for t, old, _ in self.changes:
            t.markers = list(old)
            t.touch()


class SortChildrenCommand(Command):
    def __init__(self, parent: Topic, reverse: bool = False) -> None:
        super().__init__()
        self.parent = parent
        self.old = list(parent.children)
        self.new = sorted(self.old, key=lambda t: t.title.casefold(), reverse=reverse)
        self.label = tr("Sort Topics")

    def redo(self) -> None:
        self.parent.children[:] = self.new
        self.parent.touch()

    def undo(self) -> None:
        self.parent.children[:] = self.old
        self.parent.touch()


SHEET_ATTRS = frozenset({"title", "theme_id", "structure"})


class SetSheetAttrCommand(Command):
    def __init__(self, sheet: Sheet, attr: str, value: Any, label: Optional[str] = None) -> None:
        super().__init__()
        if attr not in SHEET_ATTRS:
            raise ValueError(f"sheet attribute {attr!r} is not editable")
        self.sheet, self.attr, self.value = sheet, attr, value
        self.old = getattr(sheet, attr)
        self.label = label or tr("Change Sheet")

    def redo(self) -> None:
        setattr(self.sheet, self.attr, self.value)
        self.sheet.touch()

    def undo(self) -> None:
        setattr(self.sheet, self.attr, self.old)
        self.sheet.touch()


class AddSheetCommand(Command):
    def __init__(self, workbook: Workbook, sheet: Sheet, index: Optional[int] = None) -> None:
        super().__init__()
        self.workbook, self.sheet, self.index = workbook, sheet, index
        self.label = tr("Add Sheet")

    def redo(self) -> None:
        sheets = self.workbook.sheets
        idx = len(sheets) if self.index is None else max(0, min(self.index, len(sheets)))
        sheets.insert(idx, self.sheet)
        self.index = idx

    def undo(self) -> None:
        self.workbook.sheets.remove(self.sheet)


class RemoveSheetCommand(Command):
    def __init__(self, workbook: Workbook, sheet: Sheet) -> None:
        super().__init__()
        if len(workbook.sheets) <= 1:
            raise ValueError(tr("A workbook must keep at least one sheet."))
        self.workbook, self.sheet, self.index = workbook, sheet, -1
        self.label = tr("Delete Sheet")

    def redo(self) -> None:
        self.index = self.workbook.sheets.index(self.sheet)
        del self.workbook.sheets[self.index]

    def undo(self) -> None:
        self.workbook.sheets.insert(self.index, self.sheet)


Listener = Callable[[Optional[Command]], None]


class UndoStack:
    """Unlimited (limit=0) or bounded history with clean-state tracking."""

    def __init__(self, limit: int = 0) -> None:
        self.limit = max(0, int(limit))
        self._done: list[Command] = []
        self._undone: list[Command] = []
        self._clean_index = 0          # len(_done) at last save; -1 = unreachable
        self._listeners: list[Listener] = []

    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _notify(self, cmd: Optional[Command]) -> None:
        for fn in list(self._listeners):
            fn(cmd)

    def push(self, cmd: Command) -> None:
        cmd.redo()  # if this raises, history is untouched
        if self._clean_index > len(self._done):
            self._clean_index = -1
        self._done.append(cmd)
        self._undone.clear()
        if self.limit and len(self._done) > self.limit:
            overflow = len(self._done) - self.limit
            del self._done[:overflow]
            if self._clean_index >= 0:
                self._clean_index -= overflow
                if self._clean_index < 0:
                    self._clean_index = -1
        self._notify(cmd)

    def undo(self) -> Optional[Command]:
        if not self._done:
            return None
        cmd = self._done.pop()
        try:
            cmd.undo()
        except Exception:
            self._done.append(cmd)
            raise
        self._undone.append(cmd)
        self._notify(cmd)
        return cmd

    def redo(self) -> Optional[Command]:
        if not self._undone:
            return None
        cmd = self._undone.pop()
        try:
            cmd.redo()
        except Exception:
            self._undone.append(cmd)
            raise
        self._done.append(cmd)
        self._notify(cmd)
        return cmd

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    @property
    def undo_label(self) -> str:
        return self._done[-1].label if self._done else ""

    @property
    def redo_label(self) -> str:
        return self._undone[-1].label if self._undone else ""

    @property
    def is_clean(self) -> bool:
        return self._clean_index == len(self._done)

    def set_clean(self) -> None:
        self._clean_index = len(self._done)

    def count(self) -> int:
        return len(self._done)

    def clear(self) -> None:
        self._done.clear()
        self._undone.clear()
        self._clean_index = 0
        self._notify(None)
