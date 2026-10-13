"""An open workbook plus its undo history, file path and event bus."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from vmap.core.commands import Command, UndoStack
from vmap.core.events import EventBus
from vmap.core.model import Sheet, Workbook
from vmap.i18n import tr


class Document:
    def __init__(self, workbook: Optional[Workbook] = None,
                 path: str | Path | None = None, undo_limit: int = 0) -> None:
        self.workbook = workbook if workbook is not None else Workbook.new_default()
        self.path: Optional[Path] = Path(path) if path else None
        self.events = EventBus()
        self.undo_stack = UndoStack(limit=undo_limit)
        self.undo_stack.add_listener(self._on_stack_changed)

    def _on_stack_changed(self, command: Optional[Command]) -> None:
        self.events.emit("changed", command=command)

    def execute(self, command: Command, sheet: Optional[Sheet] = None) -> None:
        if sheet is not None and command.sheet is None:
            command.sheet = sheet
        self.undo_stack.push(command)

    def undo(self) -> Optional[Command]:
        return self.undo_stack.undo()

    def redo(self) -> Optional[Command]:
        return self.undo_stack.redo()

    @property
    def is_modified(self) -> bool:
        return not self.undo_stack.is_clean

    @property
    def display_name(self) -> str:
        return self.path.name if self.path else tr("Untitled")

    def mark_saved(self, path: str | Path) -> None:
        self.path = Path(path)
        self.undo_stack.set_clean()
        self.events.emit("saved", path=self.path)
