"""Regenerate Agent_Swarm_Documentation.pdf from documentation.html.

    python docs/build_pdf.py

Needs `pip install playwright` (Python bindings only -- channel="chrome"
reuses the installed Chrome instead of downloading Playwright's browsers).

Checks every referenced asset exists first: Chromium renders a missing image
as a silent broken-image box, so without this the failure only shows up when
someone opens the finished PDF.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
HTML = DOCS / "documentation.html"
PDF = DOCS / "Agent_Swarm_Documentation.pdf"


def main() -> int:
    html = HTML.read_text(encoding="utf-8")
    missing = [src for src in re.findall(r'<img[^>]+src="([^"]+)"', html) if not (DOCS / src).exists()]
    if missing:
        print("Referenced but missing -- add these before building:", file=sys.stderr)
        for src in missing:
            print(f"  {DOCS / src}", file=sys.stderr)
        return 1

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.goto(HTML.as_uri())
        page.pdf(path=str(PDF), prefer_css_page_size=True, print_background=True)
        browser.close()

    print(f"Wrote {PDF} ({PDF.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
