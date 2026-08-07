# Documentation source

`Agent_Swarm_Documentation.pdf` is generated from `documentation.html` (self-contained,
references `assets/*.png`). To regenerate after editing the HTML:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)  # uses system Chrome, no browser download needed
    page = browser.new_page()
    page.goto("file:///c:/intelFPGA/18.1/Practice/agent_swarm/docs/documentation.html")
    page.pdf(path="c:/intelFPGA/18.1/Practice/agent_swarm/docs/Agent_Swarm_Documentation.pdf",
             prefer_css_page_size=True, print_background=True)
    browser.close()
```

Requires `pip install playwright` (Python bindings only -- `channel="chrome"` reuses your
installed Chrome rather than downloading Playwright's own browsers).

**Font note:** the `code` style intentionally uses `"Consolas", monospace` and *not* a variable
font like Cascadia Mono/Code. Chromium's print-to-PDF pipeline has a glyph-corruption bug with
variable fonts once the same font is subset across enough pages/repetitions -- it shows up as a
stray horizontal line through inline code text. Consolas (a static font) doesn't hit it.
