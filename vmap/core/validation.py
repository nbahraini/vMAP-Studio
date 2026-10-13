"""Structural validation of a workbook (used by loaders and `vmap validate`)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from vmap.core.model import ROOT, Workbook
from vmap.i18n import tr


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def validate_workbook(wb: Workbook) -> ValidationResult:
    r = ValidationResult()
    if not wb.sheets:
        r.errors.append(tr("Workbook contains no sheets."))
    seen: set[str] = set()
    for sheet in wb.sheets:
        if not is_uuid(sheet.id):
            r.warnings.append(tr("Sheet id is not a UUID: {id}").format(id=sheet.id))
        if sheet.id in seen:
            r.errors.append(tr("Duplicate id: {id}").format(id=sheet.id))
        seen.add(sheet.id)
        if sheet.root.type != ROOT:
            r.errors.append(tr("Sheet '{t}' root topic has type '{ty}'.").format(
                t=sheet.title, ty=sheet.root.type))
        if sheet.root.parent is not None:
            r.errors.append(tr("Sheet '{t}' root topic has a parent.").format(t=sheet.title))
        for t in sheet.root.iter_subtree():
            if t is not sheet.root and t.type == ROOT:
                r.errors.append(tr("Nested root topic: {id}").format(id=t.id))
            if not is_uuid(t.id):
                r.warnings.append(tr("Topic id is not a UUID: {id}").format(id=t.id))
            if t.id in seen:
                r.errors.append(tr("Duplicate id: {id}").format(id=t.id))
            seen.add(t.id)
            for c in t.children:
                if c.parent is not t:
                    r.errors.append(tr("Broken parent reference: {id}").format(id=c.id))
            if not isinstance(t.style, dict):
                r.errors.append(tr("Invalid style on topic {id}").format(id=t.id))
    return r
