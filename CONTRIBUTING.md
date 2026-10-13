# Contributing and development

```bash
pip install -e ".[dev]"
pytest -q
python -m vmap
```

## Rules (from the project specification)

1. No fake functionality. Every control works, says "Not implemented yet", or is hidden.
2. Never claim a file format is supported until a real reader/writer exists **and is tested**.
3. All document changes go through `Command`s. Composite changes use `MacroCommand`.
4. The core (`vmap/core`, `vmap/mindmap`, `vmap/themes`, `vmap/formats`, `vmap/cli`) never imports Qt.
5. Every user-visible string goes through `vmap.i18n.tr()`.
6. Long-running work must not block the UI thread.
7. Update ROADMAP.md and FEATURE_MATRIX.md in the same change as the feature.

## Definition of done

A feature is done when it has an implementation, UI, unit tests, integration tests where
applicable, error handling and documentation, and has been considered on Linux, Windows
and macOS.

## Translations

Generate a translation template with `pyside6-lupdate`, translate it in Qt Linguist, and
compile it to `vmap/translations/vmap_<locale>.qm`. The app loads it automatically.
