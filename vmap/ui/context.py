"""Per-process application context: settings database, themes, data directories."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from vmap.core.services.database import AppDatabase
from vmap.i18n import tr
from vmap.themes.engine import Theme, ThemeRegistry

MAX_THEME_BYTES = 1024 * 1024


def read_theme_file(path: str | Path) -> Theme:
    """Strictly parse a theme file (raises OSError or ValueError)."""
    p = Path(path)
    if p.stat().st_size > MAX_THEME_BYTES:
        raise ValueError(tr("theme file is too large"))
    return Theme.from_dict(json.loads(p.read_text(encoding="utf-8")))


@dataclass
class AppContext:
    db: AppDatabase
    themes: ThemeRegistry
    builtin_theme_ids: frozenset[str]
    data_dir: Optional[Path] = None
    user_theme_dir: Optional[Path] = None
    log_path: Optional[Path] = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, data_dir: Optional[Path], log_path: Optional[Path] = None) -> "AppContext":
        warnings: list[str] = []
        db: Optional[AppDatabase] = None
        theme_dir: Optional[Path] = None
        if data_dir is not None:
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
                theme_dir = data_dir / "themes"
                theme_dir.mkdir(exist_ok=True)
                db = AppDatabase(data_dir / "settings.sqlite3")
            except (OSError, sqlite3.Error) as exc:
                warnings.append(tr("Settings storage unavailable; using temporary settings: {e}").format(e=exc))
        if db is None:
            db = AppDatabase(":memory:")
        themes = ThemeRegistry.with_builtins()
        warnings.extend(tr("Built-in theme error: {e}").format(e=e) for e in themes.errors)
        ctx = cls(db, themes, frozenset(t.id for t in themes.all()), data_dir, theme_dir,
                  log_path, warnings)
        ctx._load_user_themes()
        return ctx

    def _load_user_themes(self) -> None:
        if self.user_theme_dir is None:
            return
        for f in sorted(self.user_theme_dir.glob("*.json")):
            try:
                theme = read_theme_file(f)
            except (OSError, ValueError) as exc:
                self.warnings.append(tr("Theme {name} skipped: {e}").format(name=f.name, e=exc))
                continue
            if theme.id in self.builtin_theme_ids:
                self.warnings.append(tr("Theme {name} skipped: id '{id}' is reserved.").format(
                    name=f.name, id=theme.id))
                continue
            self.themes.register(theme)

    def install_theme(self, theme: Theme) -> Path:
        """Persist a user theme (atomic write) and register it. Built-ins are never replaced."""
        if theme.id in self.builtin_theme_ids:
            raise ValueError(tr("The theme id '{id}' is reserved.").format(id=theme.id))
        if self.user_theme_dir is None:
            raise OSError(tr("No writable data directory."))
        path = self.user_theme_dir / f"{theme.id}.json"   # id is validated as a safe file name
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(json.dumps(theme.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        self.themes.register(theme)
        return path
