# Documentation source

> **Note:** the PDF and `documentation.html` describe the earlier Celery + Redis
> architecture. The current architecture (GitHub Actions executor, signed runner API,
> automatic pull requests) is documented in the top-level [README](../README.md).

`Agent_Swarm_Documentation.pdf` is generated from `documentation.html` (self-contained,
references `assets/*.png`). To regenerate after editing the HTML:

```
python docs/build_pdf.py
```

Requires `pip install playwright` (Python bindings only -- it reuses your installed
Chrome via `channel="chrome"` rather than downloading Playwright's own browsers).

The script refuses to build if any `<img>` in the HTML points at a file that isn't in
`assets/`. That check matters: Chromium renders a missing image as a silent
broken-image box, so otherwise a typo'd filename only surfaces when someone opens the
finished PDF.

**Font note:** the `code` style intentionally uses `"Consolas", monospace` and *not* a variable
font like Cascadia Mono/Code. Chromium's print-to-PDF pipeline has a glyph-corruption bug with
variable fonts once the same font is subset across enough pages/repetitions -- it shows up as a
stray horizontal line through inline code text. Consolas (a static font) doesn't hit it.
