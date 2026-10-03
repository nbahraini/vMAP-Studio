# Themes

Themes are versioned JSON files (`schema_version: 1`). They are validated **strictly**:
one invalid value rejects the whole file.

```json
{
  "schema_version": 1, "id": "my_theme", "name": "My Theme", "version": 1,
  "author": "you", "license": "CC0-1.0", "description": "",
  "background": "#FFFFFF", "line_style": "curve",
  "colored_branches": true, "branch_colors": ["#C62828", "#1565C0"],
  "branch_color_targets": {"main": ["fill", "border", "line_color"], "sub": ["line_color"]},
  "h_gap": 34, "v_gap": 12, "root_gap": 56,
  "levels": {"root": {"font_size": 18, "bold": true}, "main": {}, "sub": {"shape": "underline"}}
}
```

- `id`: lowercase letters, digits, `_` or `-`, at most 64 characters. Built-in ids cannot be replaced.
- `line_style`: `curve`, `elbow` or `straight`.
- Levels: `root`, `main` (first level) and `sub` (deeper levels).

| Style key | Values |
|---|---|
| `shape` | `rounded_rect`, `rect`, `pill`, `ellipse`, `underline` |
| `fill`, `border`, `text_color`, `line_color` | `#RRGGBB` or `none` (`text_color` must be a colour) |
| `border_width`, `line_width` | 0–20 |
| `font_size` | 4–200 (points) |
| `padding_x`, `padding_y` | 0–100 |
| `max_width` | 40–2000 (wrap width in px) |
| `font_family` | font name; empty = system font |
| `bold`, `italic` | `true` / `false` |

**Resolution order:** built-in defaults → theme level → branch colour (for the listed
targets) → the topic's own overrides (set in the Properties panel).

Install a theme with **Map → Theme → Import Theme…**. It is copied to the user themes
folder and loaded on every start. Themes used by a document are embedded in the `.vmap`
file. Embedded themes never replace themes you have installed.
