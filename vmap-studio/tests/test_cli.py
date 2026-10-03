import json

import pytest

from vmap.cli.main import main


def test_new_validate_info(tmp_path, capsys):
    assert main(["new", str(tmp_path / "demo"), "--title", "Kubernetes", "--theme", "rainbow"]) == 0
    path = tmp_path / "demo.vmap"
    assert path.exists()
    assert main(["new", str(path)]) == 1                     # refuses to overwrite
    assert main(["new", str(path), "--force", "--title", "K8s"]) == 0
    assert main(["new", str(tmp_path / "x.vmap"), "--theme", "nope"]) == 1
    assert main(["validate", str(path)]) == 0
    capsys.readouterr()
    assert main(["info", str(path), "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["topics"] == 1 and info["sheets"][0]["theme"] == "classic"
    assert info["embedded_themes"] == ["classic"]


def test_validate_rejects_garbage(tmp_path, capsys):
    bad = tmp_path / "bad.vmap"
    bad.write_bytes(b"nope")
    assert main(["validate", str(bad)]) == 1
    assert "INVALID" in capsys.readouterr().out


def test_theme_list(capsys):
    assert main(["theme", "list"]) == 0
    assert "classic" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["import", "export", "convert", "render", "batch", "ai", "plugin"])
def test_planned_commands_are_honest(command, capsys):
    assert main([command, "a", "b"]) == 2
    assert "not implemented yet" in capsys.readouterr().err
