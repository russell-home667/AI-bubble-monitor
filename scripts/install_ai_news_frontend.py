#!/usr/bin/env python3
from pathlib import Path

p = Path("index.html")
text = p.read_text(encoding="utf-8")
tag = '<script src="assets/ai-news.js"></script>'
if tag in text:
    print("AI news frontend already installed")
    raise SystemExit(0)

anchor = '<script src="assets/chart-time-slider.js"></script>  <script src="assets/source-links.js"></script>'
if anchor not in text:
    raise SystemExit("Could not find index.html script anchor")

text = text.replace(anchor, anchor + '  ' + tag, 1)
p.write_text(text, encoding="utf-8")
print("Installed AI news frontend loader into index.html")
