# Architecture

## Layers

```
┌──────────────────────── UI layer  (vmap/ui, PySide6) ─────────────────────────┐
│ MainWindow · MapView/MapScene/items · Inspector · Navigator · FindBar · Dialogs│
└───────────────┬──────────────────────────────────────────────▲─────────────────┘
        Commands │                                              │ "changed" events
┌───────────────▼──────────────────────────────────────────────┴─────────────────┐
│ Core engine  (vmap/core, pure Python — never imports Qt)                        │
│ model · commands + UndoStack · document · events · validation · search · outline│
└──────┬──────────────────────┬────────────────────────┬──────────────────────────┘
  vmap/mindmap           vmap/themes              vmap/formats            vmap/cli
  layout engine          theme + style engine     format adapters         `vmap` tool
```

The rule "core never imports Qt" is enforced by `tests/test_architecture_and_performance.py`.
It keeps the engine reusable by the CLI and by the planned batch converter, MCP server,
AI agents and collaboration service.

## Data flow of an edit

1. A UI action (key, menu, drag, Properties panel) builds a **Command**.
2. `Document.execute()` pushes it onto the `UndoStack`, which calls `redo()`.
3. The stack notifies the document, which emits `changed(command)` on its `EventBus`.
4. `MainWindow` reacts: it switches to `command.sheet` if needed and calls `MapView.refresh()`.
5. `MapScene.sync()` resolves styles (theme engine), measures text (cached), runs the
   layout (`compute_layout`) and updates only the graphics items that changed.

Composite edits (paste, multi-delete, Replace All, and in future AI edits) are a
`MacroCommand`. A macro is one undo step and rolls back by itself if any part fails.

## Modules

| Package | Responsibility |
|---|---|
| `vmap.core.model` | Workbook → Sheet → Topic tree, UUIDs, timestamps, (de)serialisation with depth/type checks |
| `vmap.core.commands` | All mutations; `UndoStack` with limit and clean-state tracking |
| `vmap.core.document` | Open workbook + path + undo stack + events |
| `vmap.core.search` / `outline` / `validation` | Find/replace, text outlines, structural checks |
| `vmap.mindmap.layouts` | Qt-free tree layout; guarantees non-overlapping boxes |
| `vmap.themes.engine` | Strict JSON themes; style resolution: defaults → theme level → branch colour → topic override |
| `vmap.formats` | `FormatAdapter` interface, `ConversionReport`, `.vmap` adapter |
| `vmap.ui.canvas` | Graphics items, incremental scene sync, interaction, editing operations |
| `vmap.ui.*` | Window, panels, dialogs, export, background tasks, app context |

## Threading

File reading, parsing and writing run in a worker thread (`vmap/ui/tasks.py`). During
that time the UI keeps repainting but ignores user input, so the document cannot change
mid-write. Rendering stays on the GUI thread, as Qt requires.

## Extension points (planned)

- Format adapters register with `FormatRegistry`; Phase 9 adds discovery via Python entry points.
- The AI engine (Phases 7–8) will only modify documents through Commands, as previewed
  macros that the user approves. That makes every AI change reviewable and undoable.
- Collaboration (Phase 9) can build on the command stream as an operation log.
