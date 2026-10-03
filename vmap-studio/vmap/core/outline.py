"""Plain-text outline <-> topics (clipboard interop, quick capture)."""
from __future__ import annotations

from typing import Iterable

from vmap.core.model import Topic

_BULLETS = ("- ", "* ", "+ ")


def topics_to_outline(topics: Iterable[Topic], indent: str = "\t") -> str:
    lines: list[str] = []
    for top in topics:
        stack = [(top, 0)]
        while stack:
            t, depth = stack.pop()
            lines.append(indent * depth + t.title.replace("\n", " "))
            stack.extend((c, depth + 1) for c in reversed(t.children))
    return "\n".join(lines)


def outline_to_topics(text: str, max_topics: int = 5000) -> list[Topic]:
    """Indentation (tabs or spaces) defines hierarchy; Markdown bullets are stripped."""
    roots: list[Topic] = []
    stack: list[tuple[int, Topic]] = []
    count = 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        expanded = raw.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip(" "))
        title = expanded.strip()
        for prefix in _BULLETS:
            if title.startswith(prefix):
                title = title[len(prefix):].strip()
                break
        topic = Topic(title=title)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            stack[-1][1].add_child(topic)
        else:
            roots.append(topic)
        stack.append((indent, topic))
        count += 1
        if count >= max_topics:
            break
    return roots
