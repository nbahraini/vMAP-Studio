"""Adapter interface + conversion reports (spec section 16).

Spec method -> implementation: detect() -> detect, import() -> import_file,
export() -> export_file, validate() -> validate, preserve_metadata()/report_loss()
-> ConversionReport (unsupported content is always reported, never dropped silently).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from vmap.core.model import Workbook
from vmap.i18n import tr


class FormatError(Exception):
    """Raised for unreadable, corrupted or unsupported files."""


@dataclass
class ConversionReport:
    format_id: str
    operation: str  # "import" | "export"
    counts: dict[str, int] = field(default_factory=dict)
    unsupported: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def lossless(self) -> bool:
        return not self.unsupported

    @property
    def compatibility(self) -> str:
        return tr("100% compatible") if self.lossless else tr("Partial compatibility")

    def summary(self) -> str:
        lines = [f"{self.compatibility} ({self.format_id} {self.operation})"]
        if self.counts:
            lines.append(tr("Processed:"))
            lines += [f"  - {v} {k}" for k, v in self.counts.items()]
        if self.unsupported:
            lines.append(tr("Unsupported (not preserved):"))
            lines += [f"  - {u}" for u in self.unsupported]
        if self.warnings:
            lines.append(tr("Warnings:"))
            lines += [f"  - {w}" for w in self.warnings]
        return "\n".join(lines)


@dataclass
class ImportResult:
    workbook: Workbook
    report: ConversionReport
    themes: list[Any] = field(default_factory=list)   # embedded Theme objects


class FormatAdapter(ABC):
    id: str = ""
    name: str = ""
    extensions: tuple[str, ...] = ()
    can_import: bool = False
    can_export: bool = False

    @abstractmethod
    def detect(self, path: str | Path) -> bool: ...

    def import_file(self, path: str | Path) -> ImportResult:
        raise NotImplementedError

    def export_file(self, workbook: Workbook, path: str | Path,
                    themes: Any = None) -> ConversionReport:
        raise NotImplementedError

    def validate(self, path: str | Path):
        from vmap.core.validation import validate_workbook
        return validate_workbook(self.import_file(path).workbook)


class FormatRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, FormatAdapter] = {}

    def register(self, adapter: FormatAdapter) -> None:
        self._adapters[adapter.id] = adapter

    def get(self, format_id: str) -> Optional[FormatAdapter]:
        return self._adapters.get(format_id)

    def all(self) -> list[FormatAdapter]:
        return list(self._adapters.values())

    def for_path(self, path: str | Path) -> Optional[FormatAdapter]:
        suffix = Path(path).suffix.lower()
        for a in self._adapters.values():
            if suffix in a.extensions:
                return a
        for a in self._adapters.values():
            try:
                if a.detect(path):
                    return a
            except (OSError, ValueError):
                continue
        return None
