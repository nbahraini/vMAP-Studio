import json
import zipfile

import pytest

from vmap.core.model import Topic, Workbook, workbook_to_dict
from vmap.formats import FormatError, default_registry, universal
from vmap.formats.universal import UniversalAdapter
from vmap.themes.engine import ThemeRegistry

adapter = UniversalAdapter()


def write_archive(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def members_for(workbook_dict, schema="1.0"):
    return {"mimetype": universal.MIMETYPE,
            "manifest.json": json.dumps({"format": "vmap", "schema_version": schema}),
            "document.json": json.dumps({"schema_version": schema, "workbook": workbook_dict})}


def test_round_trip_is_lossless(sample_workbook, tmp_path):
    path = tmp_path / "a.vmap"
    report = adapter.export_file(sample_workbook, path, themes=ThemeRegistry.with_builtins())
    assert report.lossless and report.counts == {"sheets": 1, "topics": 10}
    result = adapter.import_file(path)
    assert workbook_to_dict(result.workbook) == workbook_to_dict(sample_workbook)
    assert result.report.lossless and not result.report.warnings
    assert [t.id for t in result.themes] == ["classic"]
    adapter.export_file(result.workbook, tmp_path / "b.vmap")       # second generation
    again = adapter.import_file(tmp_path / "b.vmap").workbook
    assert workbook_to_dict(again) == workbook_to_dict(result.workbook)


def test_unicode_and_rtl_text_survive(tmp_path):
    wb = Workbook.new_default()
    wb.sheets[0].root.title = "امنیت شبکه"
    wb.sheets[0].root.add_child(Topic("فایروال 🔥 / 日本語"))
    adapter.export_file(wb, tmp_path / "u.vmap")
    loaded = adapter.import_file(tmp_path / "u.vmap").workbook
    assert loaded.sheets[0].root.title == "امنیت شبکه"
    assert loaded.sheets[0].root.children[0].title == "فایروال 🔥 / 日本語"


def test_detection_and_registry(tmp_path):
    good, bad = tmp_path / "x.vmap", tmp_path / "x.txt"
    adapter.export_file(Workbook.new_default(), good)
    bad.write_text("hello", encoding="utf-8")
    assert adapter.detect(good) and not adapter.detect(bad)
    assert default_registry().for_path("any.vmap").id == "vmap"
    assert default_registry().for_path(bad) is None


def test_failed_save_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "doc.vmap"
    adapter.export_file(Workbook.new_default(), path)
    before = path.read_bytes()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(universal.json, "dumps", boom)
    with pytest.raises(OSError):
        adapter.export_file(Workbook.new_default(), path)
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))


def _wb_dict(**sheet_patch):
    data = workbook_to_dict(Workbook.new_default())
    data["sheets"][0].update(sheet_patch)
    return data


def _duplicate_ids():
    wb = Workbook.new_default()
    a, b = Topic("a"), Topic("b")
    b.id = a.id
    wb.sheets[0].root.add_child(a)
    wb.sheets[0].root.add_child(b)
    return workbook_to_dict(wb)


@pytest.mark.parametrize("members", [
    {"document.json": "{}"},                                              # no manifest
    {"manifest.json": json.dumps({"format": "other"}), "document.json": "{}"},
    members_for(_wb_dict(), schema="2.0"),
    members_for(_wb_dict(), schema="abc"),
    {**members_for(_wb_dict()), "document.json": "{"},                    # broken JSON
    {**members_for(_wb_dict()), "document.json": json.dumps({"schema_version": "1.0"})},
    members_for({"sheets": []}),                                          # no sheets
    members_for(_duplicate_ids()),
    members_for(_wb_dict(root={"title": "x", "type": "topic"})),          # root type
])
def test_invalid_archives_are_rejected(tmp_path, members):
    path = tmp_path / "bad.vmap"
    write_archive(path, members)
    with pytest.raises(FormatError):
        adapter.import_file(path)


def test_not_a_zip(tmp_path):
    path = tmp_path / "bad.vmap"
    path.write_bytes(b"definitely not a zip")
    with pytest.raises(FormatError):
        adapter.import_file(path)


def test_size_limit(tmp_path, monkeypatch):
    path = tmp_path / "a.vmap"
    adapter.export_file(Workbook.new_default(), path)
    monkeypatch.setattr(universal, "MAX_JSON_BYTES", 10)
    with pytest.raises(FormatError):
        adapter.import_file(path)


def test_unknown_content_is_reported_not_dropped_silently(tmp_path):
    path = tmp_path / "extra.vmap"
    write_archive(path, {**members_for(_wb_dict()), "evil.txt": "x", "../../escape.txt": "x",
                         "images/a.png": b"\x89PNG", "themes/broken.json": "{}"})
    result = adapter.import_file(path)
    assert not result.report.lossless
    assert result.report.compatibility == "Partial compatibility"
    assert len(result.report.unsupported) == 3          # 2 unknown entries + asset notice
    assert any("broken.json" in w for w in result.report.warnings)
    assert not (tmp_path.parent / "escape.txt").exists()
