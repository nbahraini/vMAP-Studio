# The `.vmap` file format (schema 1.0)

A `.vmap` file is a ZIP container:

```
mimetype            "application/vnd.vmap+zip" (first entry, stored)
manifest.json       {"format": "vmap", "schema_version": "1.0", "generator", "workbook_id", "created", "modified"}
document.json       {"schema_version": "1.0", "workbook": {...}}
themes/<id>.json    every theme used by a sheet (keeps files portable)
assets/ images/ audio/ attachments/ previews/ metadata/    reserved for Phase 3+
```

## document.json

```json
{"schema_version": "1.0",
 "workbook": {"id": "uuid", "title": "", "created": "ISO-8601", "modified": "ISO-8601",
   "sheets": [{"id": "uuid", "title": "Sheet 1", "theme_id": "classic", "structure": "mind_map",
     "root": {"id": "uuid", "type": "root", "title": "Central Topic",
       "children": [{"id": "uuid", "type": "topic", "title": "Branch",
         "notes": "...", "labels": [], "markers": [], "folded": false,
         "style": {"fill": "#FF0000"}, "metadata": {}, "children": []}]}}]}}
```

Optional topic fields are left out when empty. Unknown `style` keys are kept in the file
but ignored when rendering.

## Reader guarantees

- Each JSON member is limited to 128 MiB, checked against the bytes actually read (zip-bomb guard).
- An archive may contain at most 10,000 entries. Topic trees may be at most 400 levels deep.
- The major schema version is checked. Duplicate ids, missing roots, nested roots and
  broken parent links are rejected.
- Archive entries are never extracted to disk, so path-traversal names have no effect.
- Unknown entries and Phase-3 asset folders are listed in the conversion report
  ("Partial compatibility"). Nothing is dropped silently. Saving over such a file asks
  for confirmation first.

## Writer guarantees

Data is written to a temporary file and then atomically renamed over the target, so a
failed save never corrupts the existing document.

## Versioning

Minor versions only add optional fields. A new major version requires a migration
function registered in `vmap.formats.universal.MIGRATIONS`.
