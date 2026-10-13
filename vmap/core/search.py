"""Topic search and replace (Qt-free; shared by the find bar, CLI and future AI tools)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from vmap.core.model import Topic

MAX_QUERY_LENGTH = 1000


class SearchError(ValueError):
    """Invalid search pattern or replacement."""


@dataclass(frozen=True)
class SearchOptions:
    query: str
    case_sensitive: bool = False
    whole_word: bool = False
    regex: bool = False
    include_notes: bool = False


def compile_pattern(options: SearchOptions) -> "re.Pattern[str]":
    if not options.query:
        raise SearchError("empty search text")
    if len(options.query) > MAX_QUERY_LENGTH:
        raise SearchError("search text is too long")
    body = options.query if options.regex else re.escape(options.query)
    if options.whole_word:
        body = rf"(?<!\w)(?:{body})(?!\w)"
    flags = 0 if options.case_sensitive else re.IGNORECASE
    try:
        return re.compile(body, flags)
    except re.error as exc:
        raise SearchError(str(exc)) from None


def topic_matches(topic: Topic, pattern: "re.Pattern[str]", include_notes: bool = False) -> bool:
    if pattern.search(topic.title):
        return True
    return bool(include_notes and topic.notes and pattern.search(topic.notes))


def find_topics(root: Topic, options: SearchOptions) -> list[Topic]:
    """All matching topics in document (depth-first) order."""
    pattern = compile_pattern(options)
    return [t for t in root.iter_subtree() if topic_matches(t, pattern, options.include_notes)]


def replace_text(text: str, pattern: "re.Pattern[str]", replacement: str,
                 regex: bool = False) -> tuple[str, int]:
    """Plain mode inserts the replacement literally; regex mode allows \\1 group references."""
    try:
        if regex:
            return pattern.subn(replacement, text)
        return pattern.subn(lambda _m: replacement, text)
    except (re.error, IndexError) as exc:
        raise SearchError(str(exc)) from None
