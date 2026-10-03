"""`vmap` CLI. Unimplemented sub-commands say so and exit with code 2."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from vmap import APP_NAME, __version__
from vmap.core.model import Workbook
from vmap.formats import FormatError, default_registry
from vmap.themes.engine import ThemeRegistry

PLANNED = {"import": "Phase 4", "export": "Phase 4", "convert": "Phase 4",
           "render": "Phase 4", "batch": "Phase 4", "ai": "Phases 7-8", "plugin": "Phase 9"}


def _max_depth(wb: Workbook) -> int:
    best = 0
    for sheet in wb.sheets:
        stack = [(sheet.root, 0)]
        while stack:
            t, d = stack.pop()
            best = max(best, d)
            stack.extend((c, d + 1) for c in t.children)
    return best


def cmd_new(args) -> int:
    out = Path(args.output)
    if out.suffix.lower() != ".vmap":
        out = out.with_suffix(".vmap")
    if out.exists() and not args.force:
        print(f"error: {out} exists (use --force)", file=sys.stderr)
        return 1
    themes = ThemeRegistry.with_builtins()
    if args.theme not in themes:
        print(f"error: unknown theme {args.theme!r}; see `vmap theme list`", file=sys.stderr)
        return 1
    wb = Workbook.new_default()
    sheet = wb.sheets[0]
    sheet.theme_id = args.theme
    if args.title:
        sheet.root.title = args.title
    default_registry().get("vmap").export_file(wb, out, themes=themes)
    print(f"created {out}")
    return 0


def cmd_validate(args) -> int:
    adapter = default_registry().get("vmap")
    failed = 0
    for f in args.files:
        try:
            result = adapter.import_file(f)
        except (FormatError, OSError) as exc:
            print(f"INVALID  {f}: {exc}")
            failed += 1
            continue
        c = result.report.counts
        print(f"OK       {f}  ({c.get('sheets', 0)} sheets, {c.get('topics', 0)} topics)"
              f"  - {result.report.compatibility}")
        for w in result.report.warnings + result.report.unsupported:
            print(f"         ! {w}")
    return 1 if failed else 0


def cmd_info(args) -> int:
    try:
        result = default_registry().get("vmap").import_file(args.file)
    except (FormatError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    wb = result.workbook
    info = {"file": str(args.file), "workbook_id": wb.id, "created": wb.created,
            "modified": wb.modified, "topics": wb.topic_count(), "max_depth": _max_depth(wb),
            "sheets": [{"title": s.title, "theme": s.theme_id, "structure": s.structure,
                        "topics": s.count()} for s in wb.sheets],
            "embedded_themes": [t.id for t in result.themes]}
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(f"{info['file']}: {info['topics']} topics, depth {info['max_depth']}")
        for s in info["sheets"]:
            print(f"  - {s['title']}: {s['topics']} topics, theme={s['theme']}, structure={s['structure']}")
    return 0


def cmd_theme(args) -> int:
    reg = ThemeRegistry.with_builtins()
    for t in reg.all():
        print(f"{t.id:<16} {t.name}  [{t.license or 'no license info'}]")
    for e in reg.errors:
        print(f"! {e}", file=sys.stderr)
    return 0


def cmd_open(args) -> int:
    from vmap.app import main as gui_main
    return gui_main(["vmap-studio"] + ([args.file] if args.file else []))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="vmap", description=f"{APP_NAME} {__version__} CLI")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("new", help="create a new .vmap file")
    p.add_argument("output")
    p.add_argument("--title")
    p.add_argument("--theme", default="classic")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_new)
    p = sub.add_parser("validate", help="validate .vmap files")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("info", help="show statistics for a .vmap file")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_info)
    p = sub.add_parser("theme", help="theme utilities")
    p.add_argument("action", choices=["list"])
    p.set_defaults(func=cmd_theme)
    p = sub.add_parser("open", help="open the desktop application")
    p.add_argument("file", nargs="?")
    p.set_defaults(func=cmd_open)
    for name, phase in PLANNED.items():
        p = sub.add_parser(name, help=f"not implemented yet ({phase})")
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.set_defaults(func=lambda a, n=name, ph=phase: _planned(n, ph))
    args = parser.parse_args(argv)
    return int(args.func(args))


def _planned(name: str, phase: str) -> int:
    print(f"`vmap {name}` is not implemented yet - planned for {phase} (see ROADMAP.md).",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
