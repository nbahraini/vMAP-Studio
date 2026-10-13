"""Universal .vmap container (ZIP), spec section 19.

    mimetype            "application/vnd.vmap+zip" (stored, first entry)
    manifest.json       format id, schema_version, generator, timestamps
    document.json       {"schema_version": "1.0", "workbook": {...}}
    themes/<id>.json    themes used by the sheets (makes files portable)
    assets/ images/ audio/ attachments/ previews/ metadata/   (Phase 3+)

Hardening: size limits on every JSON member (zip-bomb guard), member-count
limit, strict schema-version check, structural validation, atomic writes.
"""
from __future__ import annotations

import json
import os
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable

from vmap import APP_NAME, __version__
from vmap.core.model import Workbook, now_iso, workbook_from_dict, workbook_to_dict
from vmap.core.validation import validate_workbook
from vmap.formats.base import ConversionReport, FormatAdapter, FormatError, ImportResult
from vmap.i18n import tr
from vmap.themes.engine import Theme

FORMAT_ID = "vmap"
MIMETYPE = "application/vnd.vmap+zip"
SCHEMA_VERSION = "1.0"
SUPPORTED_MAJOR = 1
MAX_JSON_BYTES = 128 * 1024 * 1024
MAX_MEMBERS = 10_000
KNOWN_FILES = {"mimetype", "manifest.json", "document.json"}
RESERVED_DIRS = ("assets/", "images/", "audio/", "attachments/", "previews/", "metadata/")

# Future schema migrations: major version -> function(document_dict) -> dict
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def workbook_counts(wb: Workbook) -> dict[str, int]:
    return {"sheets": len(wb.sheets), "topics": wb.topic_count()}


def _read_json(zf: zipfile.ZipFile, name: str) -> Any:
    try:
        info = zf.getinfo(name)
    except KeyError as exc:
        raise FormatError(tr("Missing '{name}' in archive.").format(name=name)) from exc
    if info.file_size > MAX_JSON_BYTES:
        raise FormatError(tr("'{name}' is too large.").format(name=name))
    try:
        with zf.open(info) as fh:
            data = fh.read(MAX_JSON_BYTES + 1)   # header sizes can lie
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise FormatError(tr("Cannot read '{name}': {error}").format(name=name, error=exc)) from exc
    if len(data) > MAX_JSON_BYTES:
        raise FormatError(tr("'{name}' is too large.").format(name=name))
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormatError(tr("'{name}' is not valid JSON: {error}").format(name=name, error=exc)) from exc


def _check_version(version: str) -> None:
    try:
        major = int(version.split(".")[0])
    except ValueError:
        raise FormatError(tr("Unknown schema version '{v}'.").format(v=version)) from None
    if major != SUPPORTED_MAJOR and major not in MIGRATIONS:
        raise FormatError(tr("Unsupported schema version {v} (this build reads {m}.x).").format(
            v=version, m=SUPPORTED_MAJOR))


class UniversalAdapter(FormatAdapter):
    id = FORMAT_ID
    name = "VMap Universal (.vmap)"
    extensions = (".vmap",)
    can_import = True
    can_export = True

    def detect(self, path: str | Path) -> bool:
        try:
            with zipfile.ZipFile(path) as zf:
                manifest = _read_json(zf, "manifest.json")
            return isinstance(manifest, dict) and manifest.get("format") == FORMAT_ID
        except (OSError, zipfile.BadZipFile, FormatError):
            return False

    def import_file(self, path: str | Path) -> ImportResult:
        report = ConversionReport(FORMAT_ID, "import")
        try:
            zf = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise FormatError(tr("Not a valid .vmap file: {error}").format(error=exc)) from exc
        with zf:
            names = zf.namelist()
            if len(names) > MAX_MEMBERS:
                raise FormatError(tr("Archive has too many entries."))
            manifest = _read_json(zf, "manifest.json")
            if not isinstance(manifest, dict) or manifest.get("format") != FORMAT_ID:
                raise FormatError(tr("Missing or invalid manifest."))
            _check_version(str(manifest.get("schema_version", "")))
            doc = _read_json(zf, "document.json")
            if not isinstance(doc, dict) or "workbook" not in doc:
                raise FormatError(tr("document.json has no workbook."))
            try:
                workbook = workbook_from_dict(doc["workbook"])
            except (ValueError, TypeError, KeyError) as exc:
                raise FormatError(tr("Corrupted document: {error}").format(error=exc)) from exc
            themes: list[Theme] = []
            ignored_assets = 0
            for name in names:
                if name.endswith("/") or name in KNOWN_FILES:
                    continue
                if name.startswith("themes/") and name.endswith(".json"):
                    try:
                        themes.append(Theme.from_dict(_read_json(zf, name)))
                    except (FormatError, ValueError) as exc:
                        report.warnings.append(tr("Embedded theme {n} ignored: {e}").format(n=name, e=exc))
                elif name.startswith(RESERVED_DIRS):
                    ignored_assets += 1
                else:
                    report.unsupported.append(tr("Unknown archive entry: {n}").format(n=name))
            if ignored_assets:
                report.unsupported.append(tr(
                    "{n} asset file(s) are not loaded by this version and will not be re-saved."
                ).format(n=ignored_assets))
        result = validate_workbook(workbook)
        if result.errors:
            raise FormatError("; ".join(result.errors[:5]))
        report.warnings.extend(result.warnings)
        report.counts = workbook_counts(workbook)
        return ImportResult(workbook, report, themes)

    def export_file(self, workbook: Workbook, path: str | Path, themes: Any = None) -> ConversionReport:
        path = Path(path)
        report = ConversionReport(FORMAT_ID, "export", counts=workbook_counts(workbook))
        stamp = now_iso()
        manifest = {"format": FORMAT_ID, "schema_version": SCHEMA_VERSION,
                    "generator": f"{APP_NAME} {__version__}", "workbook_id": workbook.id,
                    "created": workbook.created, "modified": stamp}
        document = {"schema_version": SCHEMA_VERSION, "workbook": workbook_to_dict(workbook)}
        used: list[Theme] = []
        if themes is not None:
            seen: set[str] = set()
            for sheet in workbook.sheets:
                theme = themes.get(sheet.theme_id)
                if theme is not None and theme.id not in seen:
                    used.append(theme)
                    seen.add(theme.id)
                elif theme is None:
                    report.warnings.append(tr("Theme '{t}' not available; not embedded.").format(t=sheet.theme_id))
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(zipfile.ZipInfo("mimetype"), MIMETYPE)
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                zf.writestr("document.json", json.dumps(document, ensure_ascii=False, indent=1))
                for theme in used:
                    zf.writestr(f"themes/{theme.id}.json",
                                json.dumps(theme.to_dict(), ensure_ascii=False, indent=2))
            os.replace(tmp, path)   # atomic: never leaves a half-written document
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        workbook.modified = stamp
        return report
