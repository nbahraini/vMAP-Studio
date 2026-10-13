import json

import pytest

from vmap.core.model import Topic
from vmap.themes.engine import (DEFAULT_STYLE, Theme, ThemeRegistry, check_style_value,
                                resolve_style, sanitize_style)
from vmap.ui.context import AppContext

BUILTINS = {"classic", "rainbow", "dark", "high_contrast"}


def test_builtins_load_without_errors():
    reg = ThemeRegistry.with_builtins()
    assert BUILTINS <= {t.id for t in reg.all()} and reg.errors == []
    for theme in reg.all():
        assert theme.license, f"{theme.id} must declare a license"
        assert Theme.from_dict(theme.to_dict()).to_dict() == theme.to_dict()


@pytest.mark.parametrize("patch", [
    {"schema_version": 2}, {"id": "Bad Id"}, {"id": "../escape"}, {"name": " "},
    {"version": "1"}, {"line_style": "zigzag"}, {"background": "red"},
    {"branch_colors": ["#12345"]}, {"levels": {"root": {"font_size": 9999}}},
    {"levels": {"root": {"shape": "star"}}}, {"levels": {"huge": {}}},
    {"levels": {"main": {"unknown": 1}}}, {"h_gap": -1},
    {"branch_color_targets": {"main": ["font_size"]}},
])
def test_strict_theme_validation(patch):
    data = ThemeRegistry.with_builtins().get("classic").to_dict()
    data.update(patch)
    with pytest.raises(ValueError):
        Theme.from_dict(data)


def test_style_inheritance_order():
    theme = ThemeRegistry.with_builtins().get("rainbow")
    topic = Topic("t", style={"font_size": 30, "fill": "not-a-colour"})
    style = resolve_style(theme, topic, "main", theme.branch_color(0))
    assert style["font_size"] == 30.0                  # topic override wins
    assert style["fill"] == theme.branch_colors[0]     # invalid override ignored -> branch colour
    assert style["shape"] == "pill"                    # theme level
    assert style["line_width"] == 3.0
    assert set(resolve_style(theme, None, "sub")) == set(DEFAULT_STYLE)
    assert theme.branch_color(len(theme.branch_colors)) == theme.branch_colors[0]


def test_sanitize_and_check():
    clean, problems = sanitize_style({"fill": "#ABCDEF", "bogus": 1, "font_size": "big"})
    assert clean == {"fill": "#ABCDEF"} and len(problems) == 2
    with pytest.raises(ValueError):
        check_style_value("bold", 1)
    assert check_style_value("border", "none") == "none"


def test_registry_fallback_and_bad_files(tmp_path):
    good = ThemeRegistry.with_builtins().get("classic").to_dict()
    good.update(id="custom", name="Custom")
    (tmp_path / "good.json").write_text(json.dumps(good), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    reg = ThemeRegistry()
    assert reg.load_dir(tmp_path) == 1 and len(reg.errors) == 1 and "custom" in reg
    assert ThemeRegistry.with_builtins().get_or_default("missing").id == "classic"


def test_user_theme_install_and_reload(tmp_path):
    ctx = AppContext.create(tmp_path / "data")
    data = ctx.themes.get("classic").to_dict()
    data.update(id="my_theme", name="Mine")
    path = ctx.install_theme(Theme.from_dict(data))
    assert path.exists() and not list(path.parent.glob(".*.tmp"))
    with pytest.raises(ValueError):
        ctx.install_theme(ctx.themes.get("classic"))     # built-ins are protected
    again = AppContext.create(tmp_path / "data")
    assert "my_theme" in again.themes and not again.warnings
    ctx.db.close()
    again.db.close()
