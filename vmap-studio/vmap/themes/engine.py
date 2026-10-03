"""Theme engine: JSON themes, versioned, with style inheritance.

Resolution order (low -> high priority):
    built-in defaults -> theme level (root/main/sub) -> branch colour -> topic override
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from vmap.core.model import Topic

THEME_SCHEMA_VERSION = 1
BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
LEVELS = ("root", "main", "sub")
SHAPES = ("rounded_rect", "rect", "pill", "ellipse", "underline")
LINE_STYLES = ("curve", "elbow", "straight")
COLOR_KEYS = frozenset({"fill", "border", "text_color", "line_color"})
NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "border_width": (0, 20), "font_size": (4, 200), "padding_x": (0, 100),
    "padding_y": (0, 100), "max_width": (40, 2000), "line_width": (0, 20),
}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")   # also safe as a file name

DEFAULT_STYLE: dict[str, Any] = {
    "shape": "rounded_rect", "fill": "#FFFFFF", "border": "#5B6B7F",
    "border_width": 1.0, "text_color": "#1F2933", "font_family": "",
    "font_size": 12.0, "bold": False, "italic": False, "padding_x": 12.0,
    "padding_y": 6.0, "max_width": 280.0, "line_color": "#7A8899", "line_width": 1.5,
}
STYLE_KEYS = frozenset(DEFAULT_STYLE)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _color(v: Any, key: str, allow_none: bool = True) -> str:
    if isinstance(v, str) and (_COLOR.match(v) or (allow_none and v == "none")):
        return v
    raise ValueError(f"invalid colour for {key!r}: {v!r}")


def check_style_value(key: str, value: Any) -> Any:
    if key in COLOR_KEYS:
        return _color(value, key)
    if key == "shape":
        if value in SHAPES:
            return value
        raise ValueError(f"unknown shape {value!r}")
    if key in ("bold", "italic"):
        if isinstance(value, bool):
            return value
        raise ValueError(f"{key} must be true/false")
    if key == "font_family":
        if isinstance(value, str) and len(value) <= 128:
            return value
        raise ValueError("font_family must be a short string")
    if key in NUMERIC_RANGES:
        lo, hi = NUMERIC_RANGES[key]
        if _is_num(value) and lo <= value <= hi:
            return float(value)
        raise ValueError(f"{key} must be a number in [{lo}, {hi}]")
    raise ValueError(f"unknown style key {key!r}")


def sanitize_style(style: Any) -> tuple[dict[str, Any], list[str]]:
    """Lenient: keep valid keys, report the rest (used for per-topic overrides)."""
    clean: dict[str, Any] = {}
    problems: list[str] = []
    if not isinstance(style, dict):
        return clean, ["style is not an object"]
    for k, v in style.items():
        try:
            clean[k] = check_style_value(k, v)
        except ValueError as exc:
            problems.append(str(exc))
    return clean, problems


@dataclass
class Theme:
    id: str
    name: str
    version: int = 1
    author: str = ""
    license: str = ""
    description: str = ""
    background: str = "#FFFFFF"
    line_style: str = "curve"
    colored_branches: bool = False
    branch_colors: list[str] = field(default_factory=list)
    branch_color_targets: dict[str, list[str]] = field(default_factory=dict)
    h_gap: float = 36.0
    v_gap: float = 14.0
    root_gap: float = 56.0
    levels: dict[str, dict[str, Any]] = field(default_factory=dict)

    def branch_color(self, index: int) -> Optional[str]:
        if not self.colored_branches or not self.branch_colors:
            return None
        return self.branch_colors[index % len(self.branch_colors)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": THEME_SCHEMA_VERSION, "id": self.id, "name": self.name,
            "version": self.version, "author": self.author, "license": self.license,
            "description": self.description, "background": self.background,
            "line_style": self.line_style, "colored_branches": self.colored_branches,
            "branch_colors": list(self.branch_colors),
            "branch_color_targets": {k: list(v) for k, v in self.branch_color_targets.items()},
            "h_gap": self.h_gap, "v_gap": self.v_gap, "root_gap": self.root_gap,
            "levels": {k: dict(v) for k, v in self.levels.items()},
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Theme":
        """Strict parser: any invalid value rejects the whole theme."""
        if not isinstance(data, dict):
            raise ValueError("theme must be a JSON object")
        schema = data.get("schema_version", THEME_SCHEMA_VERSION)
        if schema != THEME_SCHEMA_VERSION:
            raise ValueError(f"unsupported theme schema_version {schema!r}")
        tid = data.get("id")
        if not isinstance(tid, str) or not _ID.match(tid):
            raise ValueError(f"invalid theme id {tid!r}")
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("theme name is required")
        version = data.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError("theme version must be an integer")
        line_style = data.get("line_style", "curve")
        if line_style not in LINE_STYLES:
            raise ValueError(f"invalid line_style {line_style!r}")
        colors = data.get("branch_colors") or []
        if not isinstance(colors, list):
            raise ValueError("branch_colors must be a list")
        targets_raw = data.get("branch_color_targets") or {}
        if not isinstance(targets_raw, dict):
            raise ValueError("branch_color_targets must be an object")
        targets: dict[str, list[str]] = {}
        for level, keys in targets_raw.items():
            if level not in LEVELS or not isinstance(keys, list) or any(k not in COLOR_KEYS for k in keys):
                raise ValueError(f"invalid branch_color_targets for {level!r}")
            targets[level] = list(keys)
        levels_raw = data.get("levels") or {}
        if not isinstance(levels_raw, dict):
            raise ValueError("levels must be an object")
        levels: dict[str, dict[str, Any]] = {}
        for level, style in levels_raw.items():
            if level not in LEVELS or not isinstance(style, dict):
                raise ValueError(f"invalid level {level!r}")
            levels[level] = {k: check_style_value(k, v) for k, v in style.items()}

        def gap(key: str, default: float) -> float:
            v = data.get(key, default)
            if not _is_num(v) or not 0 <= v <= 400:
                raise ValueError(f"{key} must be a number in [0, 400]")
            return float(v)

        return cls(
            id=tid, name=name.strip(), version=version,
            author=str(data.get("author", "")), license=str(data.get("license", "")),
            description=str(data.get("description", "")),
            background=_color(data.get("background", "#FFFFFF"), "background", allow_none=False),
            line_style=line_style, colored_branches=bool(data.get("colored_branches", False)),
            branch_colors=[_color(c, "branch_colors", allow_none=False) for c in colors],
            branch_color_targets=targets, h_gap=gap("h_gap", 36.0), v_gap=gap("v_gap", 14.0),
            root_gap=gap("root_gap", 56.0), levels=levels,
        )


FALLBACK_THEME = Theme(id="fallback", name="Fallback", levels={
    "root": {"font_size": 18.0, "bold": True, "padding_x": 20.0, "padding_y": 10.0}})


def resolve_style(theme: Theme, topic: Optional[Topic], level: str,
                  branch_color: Optional[str] = None) -> dict[str, Any]:
    style = dict(DEFAULT_STYLE)
    style.update(theme.levels.get(level, {}))
    if branch_color:
        for key in theme.branch_color_targets.get(level, ()):
            style[key] = branch_color
    if topic is not None and topic.style:
        clean, _ = sanitize_style(topic.style)
        style.update(clean)
    return style


class ThemeRegistry:
    def __init__(self, fallback_id: str = "classic") -> None:
        self._themes: dict[str, Theme] = {}
        self.fallback_id = fallback_id
        self.errors: list[str] = []

    @classmethod
    def with_builtins(cls) -> "ThemeRegistry":
        reg = cls()
        reg.load_dir(BUILTIN_DIR)
        return reg

    def load_file(self, path: str | Path) -> Theme:
        theme = Theme.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        self.register(theme)
        return theme

    def load_dir(self, directory: str | Path) -> int:
        d = Path(directory)
        if not d.is_dir():
            return 0
        n = 0
        for f in sorted(d.glob("*.json")):
            try:
                self.load_file(f)
                n += 1
            except (OSError, ValueError) as exc:   # JSONDecodeError is a ValueError
                self.errors.append(f"{f.name}: {exc}")
        return n

    def register(self, theme: Theme, replace: bool = True) -> bool:
        if not replace and theme.id in self._themes:
            return False
        self._themes[theme.id] = theme
        return True

    def get(self, theme_id: str) -> Optional[Theme]:
        return self._themes.get(theme_id)

    def get_or_default(self, theme_id: str) -> Theme:
        return (self._themes.get(theme_id) or self._themes.get(self.fallback_id)
                or FALLBACK_THEME)

    def all(self) -> list[Theme]:
        return sorted(self._themes.values(), key=lambda t: t.name.casefold())

    def __contains__(self, theme_id: object) -> bool:
        return theme_id in self._themes
