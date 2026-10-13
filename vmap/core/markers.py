"""Marker catalogue and rules (Qt-free; shared by the UI, the CLI and format adapters).

Ids follow XMind's naming (priority-1, task-half, flag-red, ...) so the planned
XMind adapter (Phase 4) can map them one to one. Custom image markers use
``custom:<first 16 hex digits of the image's SHA-256>``. A topic carries at most
one marker of an exclusive group; choosing another one replaces it.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from vmap.i18n import tr

CUSTOM_GROUP = "custom"
MAX_MARKERS_PER_TOPIC = 32
_CUSTOM_ID = re.compile(r"^custom:[0-9a-f]{16}$")

COLORS = ("red", "orange", "yellow", "green", "blue", "purple", "gray")
FACES = ("smile", "laugh", "angry", "cry", "surprise", "boring")
TASKS = ("start", "oct", "quarter", "3oct", "half", "5oct", "3quar", "7oct", "done", "pause")
ARROWS = ("up", "up-right", "right", "down-right", "down", "down-left", "left", "up-left",
          "refresh")
SYMBOLS = ("plus", "minus", "question", "exclam", "info", "wrong", "right")
TRAFFIC = ("stop", "yield", "no-entry", "warning", "light-red", "light-yellow", "light-green")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# (group id, exclusive, marker ids) in display order
GROUPS: tuple[tuple[str, bool, tuple[str, ...]], ...] = (
    ("priority", True, tuple(f"priority-{n}" for n in range(1, 10))),
    ("smiley", True, tuple(f"smiley-{k}" for k in FACES)),
    ("task", True, tuple(f"task-{k}" for k in TASKS)),
    ("flag", True, tuple(f"flag-{c}" for c in COLORS)),
    ("star", True, tuple(f"star-{c}" for c in COLORS)),
    ("people", True, tuple(f"people-{c}" for c in COLORS)),
    ("arrow", True, tuple(f"arrow-{k}" for k in ARROWS)),
    ("symbol", False, tuple(f"symbol-{k}" for k in SYMBOLS)),
    ("traffic", True, tuple(f"traffic-{k}" for k in TRAFFIC)),
    ("month", True, tuple(f"month-{k}" for k in MONTHS)),
    ("week", True, tuple(f"week-{k}" for k in WEEKDAYS)),
)
_GROUP_OF = {mid: gid for gid, _, ids in GROUPS for mid in ids}
_EXCLUSIVE = {gid: exclusive for gid, exclusive, _ in GROUPS}
_ORDER = {mid: i for i, mid in enumerate(m for _, _, ids in GROUPS for m in ids)}


def is_builtin(marker_id: Any) -> bool:
    return isinstance(marker_id, str) and marker_id in _GROUP_OF


def is_custom(marker_id: Any) -> bool:
    return isinstance(marker_id, str) and bool(_CUSTOM_ID.match(marker_id))


def group_of(marker_id: Any) -> Optional[str]:
    if is_custom(marker_id):
        return CUSTOM_GROUP
    return _GROUP_OF.get(marker_id) if isinstance(marker_id, str) else None


def is_exclusive(group_id: Optional[str]) -> bool:
    return bool(group_id) and _EXCLUSIVE.get(group_id, False)


def sort_markers(ids: Iterable[Any]) -> list[str]:
    """De-duplicate and order by catalogue order; custom markers next; unknown ids last."""
    seen: set[str] = set()
    out: list[str] = []
    for mid in ids or ():
        if isinstance(mid, str) and mid not in seen:
            seen.add(mid)
            out.append(mid)
    last = len(_ORDER)
    return sorted(out, key=lambda m: _ORDER.get(m, last if is_custom(m) else last + 1))


def display_markers(ids: Iterable[Any]) -> list[str]:
    """The markers a topic shows (sorted, de-duplicated, capped)."""
    return sort_markers(ids)[:MAX_MARKERS_PER_TOPIC]


def apply_marker(ids: Iterable[Any], marker_id: str, mode: str = "toggle") -> list[str]:
    """New marker list after mode 'toggle', 'add' or 'remove' (XMind rules)."""
    if mode not in ("toggle", "add", "remove"):
        raise ValueError(f"unknown marker mode {mode!r}")
    current = sort_markers(ids)
    if mode == "remove" or (mode == "toggle" and marker_id in current):
        return [m for m in current if m != marker_id]
    group = group_of(marker_id)
    if is_exclusive(group):
        current = [m for m in current if group_of(m) != group]
    if marker_id not in current:
        if len(current) >= MAX_MARKERS_PER_TOPIC:
            raise ValueError(tr("A topic can carry at most {n} markers.").format(
                n=MAX_MARKERS_PER_TOPIC))
        current.append(marker_id)
    return sort_markers(current)


def group_name(group_id: str) -> str:
    names = {"priority": tr("Priority"), "smiley": tr("Faces"), "task": tr("Task Progress"),
             "flag": tr("Flags"), "star": tr("Stars"), "people": tr("People"),
             "arrow": tr("Arrows"), "symbol": tr("Symbols"), "traffic": tr("Traffic Signs"),
             "month": tr("Month"), "week": tr("Day of Week"), CUSTOM_GROUP: tr("Custom")}
    return names.get(group_id, group_id)


def marker_name(marker_id: str) -> str:
    """Translated name of a built-in marker (the id itself for anything else)."""
    group = _GROUP_OF.get(marker_id)
    if group is None:
        return marker_id
    key = marker_id.split("-", 1)[1]
    if group == "priority":
        return tr("Priority {n}").format(n=key)
    if group in ("flag", "star", "people"):
        colors = {"red": tr("Red"), "orange": tr("Orange"), "yellow": tr("Yellow"),
                  "green": tr("Green"), "blue": tr("Blue"), "purple": tr("Purple"),
                  "gray": tr("Gray")}
        pattern = {"flag": tr("{color} flag"), "star": tr("{color} star"),
                   "people": tr("{color} person")}[group]
        return pattern.format(color=colors[key])
    names = {
        "smiley-smile": tr("Smile"), "smiley-laugh": tr("Laugh"), "smiley-angry": tr("Angry"),
        "smiley-cry": tr("Cry"), "smiley-surprise": tr("Surprise"), "smiley-boring": tr("Boring"),
        "task-start": tr("Not started"), "task-oct": tr("1/8 done"),
        "task-quarter": tr("1/4 done"), "task-3oct": tr("3/8 done"), "task-half": tr("Half done"),
        "task-5oct": tr("5/8 done"), "task-3quar": tr("3/4 done"), "task-7oct": tr("7/8 done"),
        "task-done": tr("Done"), "task-pause": tr("Paused"),
        "arrow-up": tr("Up"), "arrow-up-right": tr("Up right"), "arrow-right": tr("Right"),
        "arrow-down-right": tr("Down right"), "arrow-down": tr("Down"),
        "arrow-down-left": tr("Down left"), "arrow-left": tr("Left"),
        "arrow-up-left": tr("Up left"), "arrow-refresh": tr("Refresh"),
        "symbol-plus": tr("Plus"), "symbol-minus": tr("Minus"), "symbol-question": tr("Question"),
        "symbol-exclam": tr("Attention"), "symbol-info": tr("Information"),
        "symbol-wrong": tr("Wrong"), "symbol-right": tr("Correct"),
        "traffic-stop": tr("Stop"), "traffic-yield": tr("Yield"),
        "traffic-no-entry": tr("No entry"), "traffic-warning": tr("Warning"),
        "traffic-light-red": tr("Red light"), "traffic-light-yellow": tr("Yellow light"),
        "traffic-light-green": tr("Green light"),
        "month-jan": tr("January"), "month-feb": tr("February"), "month-mar": tr("March"),
        "month-apr": tr("April"), "month-may": tr("May"), "month-jun": tr("June"),
        "month-jul": tr("July"), "month-aug": tr("August"), "month-sep": tr("September"),
        "month-oct": tr("October"), "month-nov": tr("November"), "month-dec": tr("December"),
        "week-mon": tr("Monday"), "week-tue": tr("Tuesday"), "week-wed": tr("Wednesday"),
        "week-thu": tr("Thursday"), "week-fri": tr("Friday"), "week-sat": tr("Saturday"),
        "week-sun": tr("Sunday"),
    }
    return names.get(marker_id, marker_id)
