"""Structural editing operations on the current sheet.

Every mutation goes through a Command (MacroCommand for composite edits), so
each user action is exactly one undo step.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Iterable, Optional

from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication

from vmap.core.commands import (AddTopicCommand, Command, DeleteTopicCommand, MacroCommand,
                                MoveTopicCommand, SetTopicAttrCommand, SortChildrenCommand)
from vmap.core.model import MAX_DEPTH, Topic, clone_topic, topic_from_dict, topic_to_dict
from vmap.core.outline import outline_to_topics, topics_to_outline
from vmap.i18n import tr

if TYPE_CHECKING:
    from vmap.ui.canvas.view import MapView

TOPICS_MIME = "application/x-vmap-topics+json"
CLIPBOARD_LIMIT = 16 * 1024 * 1024
PASTE_TOPIC_LIMIT = 20_000


def topmost(topics: Iterable[Topic]) -> list[Topic]:
    """Drop topics whose ancestor is also in the list."""
    chosen = list(topics)
    ids = {id(t) for t in chosen}
    return [t for t in chosen if not any(id(a) in ids for a in t.ancestors())]


def subtree_depth(topic: Topic) -> int:
    best, stack = 0, [(topic, 0)]
    while stack:
        node, depth = stack.pop()
        best = max(best, depth)
        stack.extend((c, depth + 1) for c in node.children)
    return best


class MapOperations:
    def __init__(self, view: "MapView") -> None:
        self.view = view

    @property
    def sheet(self):
        return self.view.sheet

    def _say(self, text: str) -> None:
        self.view.message.emit(text)

    def _run(self, command: Command) -> bool:
        document = self.view.document
        if document is None or self.sheet is None:
            return False
        try:
            document.execute(command, self.sheet)
        except ValueError as exc:
            self._say(str(exc))
            return False
        return True

    def _focus(self) -> Optional[Topic]:
        self.view.finish_edit()
        if self.sheet is None:
            return None
        return self.view.current_topic()

    @staticmethod
    def _default_title(parent: Topic) -> str:
        n = len(parent.children) + 1
        if parent.parent is None:
            return tr("Main Topic {n}").format(n=n)
        return tr("Subtopic {n}").format(n=n)

    def _select_and_edit(self, topic: Topic) -> None:
        self.view.select_topics([topic])
        self.view.edit_topic(topic)

    # ------------------------------------------------------------ inserting
    def add_subtopic(self) -> None:
        parent = self._focus() or (self.sheet.root if self.sheet else None)
        if parent is None:
            return
        if parent.depth() + 1 >= MAX_DEPTH:
            self._say(tr("Maximum topic depth reached."))
            return
        topic = Topic(title=self._default_title(parent))
        commands: list[Command] = []
        if parent.folded:
            commands.append(SetTopicAttrCommand(parent, "folded", False))
        commands.append(AddTopicCommand(parent, topic))
        if self._run(MacroCommand(tr("Add Subtopic"), commands)):
            self._select_and_edit(topic)

    def add_sibling(self, before: bool = False) -> None:
        current = self._focus()
        if current is None:
            return
        if current.parent is None:
            self.add_subtopic()
            return
        parent = current.parent
        index = parent.index_of(current) + (0 if before else 1)
        topic = Topic(title=self._default_title(parent))
        if self._run(AddTopicCommand(parent, topic, index, label=tr("Add Topic"))):
            self._select_and_edit(topic)

    def add_parent(self) -> None:
        current = self._focus()
        if current is None:
            return
        if current.parent is None:
            self._say(tr("The root topic cannot get a parent topic."))
            return
        if current.depth() + subtree_depth(current) + 1 >= MAX_DEPTH:
            self._say(tr("Maximum topic depth reached."))
            return
        parent = current.parent
        index = parent.index_of(current)
        new = Topic(title=self._default_title(parent))
        commands = [AddTopicCommand(parent, new, index), MoveTopicCommand(current, new, 0)]
        if self._run(MacroCommand(tr("Insert Parent Topic"), commands)):
            self._select_and_edit(new)

    # ------------------------------------------------------------- removing
    def delete_selected(self, label: Optional[str] = None) -> None:
        self.view.finish_edit()
        targets = [t for t in topmost(self.view.selected_topics()) if t.parent is not None]
        if not targets:
            if self.view.selected_topics():
                self._say(tr("The root topic cannot be deleted."))
            return
        first = targets[0]
        parent = first.parent
        index = parent.index_of(first)
        remaining = [c for c in parent.children if c not in targets]
        commands = [DeleteTopicCommand(t) for t in targets]
        if self._run(MacroCommand(label or tr("Delete Topic"), commands)):
            after = remaining[min(index, len(remaining) - 1)] if remaining else parent
            self.view.select_topics([after])

    # --------------------------------------------------------------- moving
    def move_sibling(self, delta: int) -> None:
        current = self._focus()
        if current is None or current.parent is None:
            return
        parent = current.parent
        new_index = parent.index_of(current) + delta
        if not 0 <= new_index < len(parent.children):
            return
        label = tr("Move Topic Up") if delta < 0 else tr("Move Topic Down")
        if self._run(MoveTopicCommand(current, parent, new_index, label=label)):
            self.view.select_topics([current])
            self.view.ensure_visible(current)

    def drop_topic(self, topic: Topic, target: Topic, mode: str) -> None:
        """Drag-and-drop result: mode is 'child', 'before' or 'after'."""
        self.view.finish_edit()
        if topic.parent is None or self.sheet is None:
            return
        if mode == "child":
            parent, index = target, None
            if topic.parent is parent and parent.children and parent.children[-1] is topic:
                return
        else:
            parent = target.parent
            if parent is None:
                return
            index = parent.index_of(target) + (1 if mode == "after" else 0)
            if topic.parent is parent:
                current = parent.index_of(topic)
                if current < index:
                    index -= 1
                if current == index:
                    return
        if parent.depth() + 1 + subtree_depth(topic) >= MAX_DEPTH:
            self._say(tr("Maximum topic depth reached."))
            return
        commands: list[Command] = []
        if parent.folded:
            commands.append(SetTopicAttrCommand(parent, "folded", False))
        try:
            commands.append(MoveTopicCommand(topic, parent, index))
        except ValueError as exc:
            self._say(str(exc))
            return
        if self._run(MacroCommand(tr("Move Topic"), commands)):
            self.view.select_topics([topic])
            self.view.ensure_visible(topic)

    def sort_children(self, reverse: bool = False) -> None:
        parent = self._focus() or (self.sheet.root if self.sheet else None)
        if parent is None or len(parent.children) < 2:
            self._say(tr("Select a topic with at least two subtopics to sort."))
            return
        if self._run(SortChildrenCommand(parent, reverse)):
            self.view.select_topics([parent])

    # -------------------------------------------------------------- folding
    def set_folded(self, topics: Iterable[Topic], value: bool) -> None:
        self.view.finish_edit()
        targets = [t for t in topics if t.children and t.parent is not None and t.folded != value]
        if targets:
            self._run(SetTopicAttrCommand(targets, "folded", value,
                                          label=tr("Collapse") if value else tr("Expand")))

    def toggle_fold(self) -> None:
        self.view.finish_edit()
        topics = [t for t in self.view.selected_topics() if t.children and t.parent is not None]
        if topics:
            self.set_folded(topics, not all(t.folded for t in topics))

    def expand_all(self) -> None:
        self.view.finish_edit()
        if self.sheet is None:
            return
        topics = [t for t in self.sheet.topics() if t.folded and t.parent is not None]
        if topics:
            self._run(SetTopicAttrCommand(topics, "folded", False, label=tr("Expand All")))

    def collapse_all(self) -> None:
        """Fold every main topic so only the first level stays visible."""
        self.view.finish_edit()
        if self.sheet is None:
            return
        topics = [t for t in self.sheet.root.children if t.children and not t.folded]
        if topics:
            self._run(SetTopicAttrCommand(topics, "folded", True, label=tr("Collapse All")))

    def reveal(self, topic: Topic) -> None:
        hidden = [a for a in topic.ancestors() if a.folded and a.parent is not None]
        if hidden:
            self._run(SetTopicAttrCommand(hidden, "folded", False, label=tr("Reveal Topic")))

    # ------------------------------------------------------------ clipboard
    def copy(self) -> bool:
        self.view.finish_edit()
        topics = topmost(self.view.selected_topics())
        if not topics:
            return False
        payload = {"format": "vmap-topics", "version": 1,
                   "topics": [topic_to_dict(t) for t in topics]}
        mime = QMimeData()
        mime.setData(TOPICS_MIME, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        mime.setText(topics_to_outline(topics))
        QApplication.clipboard().setMimeData(mime)
        self._say(tr("Copied {n} topic(s).").format(n=len(topics)))
        return True

    def cut(self) -> None:
        if self.copy():
            self.delete_selected(label=tr("Cut"))

    def _clipboard_topics(self) -> Optional[list[Topic]]:
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return None
        if mime.hasFormat(TOPICS_MIME):
            raw = bytes(mime.data(TOPICS_MIME))
            if len(raw) > CLIPBOARD_LIMIT:
                self._say(tr("Clipboard content is too large to paste."))
                return None
            try:
                payload = json.loads(raw.decode("utf-8"))
                items = payload.get("topics") if isinstance(payload, dict) else None
                if not isinstance(items, list):
                    raise ValueError("no topics")
                return [clone_topic(topic_from_dict(d)) for d in items]
            except (ValueError, TypeError, UnicodeDecodeError):
                self._say(tr("Clipboard contains invalid topic data."))
                return None
        if mime.hasText():
            text = mime.text()
            if len(text) > CLIPBOARD_LIMIT:
                self._say(tr("Clipboard content is too large to paste."))
                return None
            return outline_to_topics(text, max_topics=PASTE_TOPIC_LIMIT)
        return None

    def paste(self) -> None:
        target = self._focus() or (self.sheet.root if self.sheet else None)
        if target is None:
            return
        topics = self._clipboard_topics()
        if not topics:
            return
        if sum(sum(1 for _ in t.iter_subtree()) for t in topics) > PASTE_TOPIC_LIMIT:
            self._say(tr("Too many topics to paste at once."))
            return
        if target.depth() + 1 + max(subtree_depth(t) for t in topics) >= MAX_DEPTH:
            self._say(tr("Maximum topic depth reached."))
            return
        commands: list[Command] = []
        if target.folded:
            commands.append(SetTopicAttrCommand(target, "folded", False))
        commands.extend(AddTopicCommand(target, t) for t in topics)
        if self._run(MacroCommand(tr("Paste"), commands)):
            self.view.select_topics(topics)

    def duplicate(self) -> None:
        self.view.finish_edit()
        topics = [t for t in topmost(self.view.selected_topics()) if t.parent is not None]
        if not topics:
            return
        # highest index first so earlier insertions never shift later ones
        ordered = sorted(topics, key=lambda t: t.parent.index_of(t), reverse=True)
        commands: list[Command] = []
        clones: list[Topic] = []
        for t in ordered:
            clone = clone_topic(t)
            clones.append(clone)
            commands.append(AddTopicCommand(t.parent, clone, t.parent.index_of(t) + 1))
        if self._run(MacroCommand(tr("Duplicate"), commands)):
            self.view.select_topics(clones)

    def select_all(self) -> None:
        self.view.finish_edit()
        self.view.select_all()
