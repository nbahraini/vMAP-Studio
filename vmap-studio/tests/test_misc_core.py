from pathlib import Path

from vmap.core.model import ROOT, Topic, Workbook
from vmap.core.outline import outline_to_topics, topics_to_outline
from vmap.core.services.database import AppDatabase
from vmap.core.validation import validate_workbook


def test_outline_parsing_with_bullets_and_tabs():
    roots = outline_to_topics("Fruit\n    - Apple\n\t- Pear\n        * Williams\n\nVeg\n")
    assert [t.title for t in roots] == ["Fruit", "Veg"]
    assert [t.title for t in roots[0].children] == ["Apple", "Pear"]
    assert roots[0].children[1].children[0].title == "Williams"


def test_outline_round_trip_and_limit():
    a, b, c = Topic("A"), Topic("B"), Topic("C")
    a.add_child(b)
    b.add_child(c)
    text = topics_to_outline([a])
    assert text == "A\n\tB\n\t\tC"
    again = outline_to_topics(text)[0]
    assert again.children[0].children[0].title == "C"
    assert len(outline_to_topics("x\n" * 100, max_topics=10)) == 10


def test_validation_rules(sample_workbook):
    result = validate_workbook(sample_workbook)
    assert result.ok and not result.warnings
    assert not validate_workbook(Workbook()).ok
    wb = Workbook.new_default()
    root = wb.sheets[0].root
    a = Topic("a")
    root.add_child(a)
    root.add_child(Topic("b", id=a.id))
    root.add_child(Topic("c", type=ROOT))
    root.add_child(Topic("d", id="custom-id"))
    result = validate_workbook(wb)
    joined = " ".join(result.errors)
    assert "Duplicate id" in joined and "Nested root" in joined
    assert any("custom-id" in w for w in result.warnings)


def test_settings_persist(tmp_path):
    db = AppDatabase(tmp_path / "s.sqlite3")
    db.set("a", 1)
    db.set("a", "two")
    assert db.get("a") == "two" and db.get("missing", "d") == "d"
    db.close()
    db = AppDatabase(tmp_path / "s.sqlite3")
    assert db.get("a") == "two"
    db.close()


def test_recent_files(tmp_path):
    db = AppDatabase()
    for i in range(5):
        db.add_recent(tmp_path / f"{i}.vmap", limit=3)
    assert [Path(p).name for p in db.recent_files()] == ["4.vmap", "3.vmap", "2.vmap"]
    db.add_recent(tmp_path / "2.vmap")
    assert Path(db.recent_files()[0]).name == "2.vmap"
    db.remove_recent(tmp_path / "2.vmap")
    assert "2.vmap" not in [Path(p).name for p in db.recent_files()]
    db.clear_recent()
    assert db.recent_files() == []
