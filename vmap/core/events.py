"""Minimal synchronous event bus that decouples the core from the UI."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

Handler = Callable[..., None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler) -> None:
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)

    def unsubscribe(self, event: str, handler: Handler) -> None:
        handlers = self._handlers.get(event)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def emit(self, event: str, **payload: Any) -> None:
        for handler in list(self._handlers.get(event, ())):
            handler(**payload)
