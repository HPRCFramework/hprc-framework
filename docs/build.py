#!/usr/bin/env python3
"""Generate styled HTML versions of the Markdown docs.

Converts the repo's Markdown docs (README) into HTML that matches the
look of the hand-written doc site (shared stylesheet + sidebar layout). The
hand-written pages (docs/index.html, user-guide.html, architecture.html,
sprep/sprep-spec.html) are richer and are left as-is.

Requires `pandoc` (https://pandoc.org). Run from anywhere:

    python docs/build.py

Output is written next to the Markdown sources (repo root) so their relative links
(docs/..., examples/..., LICENSE) keep working.
"""

from __future__ import annotations

import html as html_mod
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root

# (source markdown, output html, page title)
DOCS = [
    ("README.md", "README.html", "HPRC Framework — README"),
]

CSS_HREF = "docs/assets/hprc-docs.css"

# Rewrite links to Markdown files so HTML readers stay in HTML where a version exists.
LINK_REWRITES = {
    'href="README.md"': 'href="README.html"',
    'href="ARCHITECTURE.md"': 'href="docs/architecture.html"',
    'href="sprep/sprep-spec.md"': 'href="sprep/sprep-spec.html"',
}

NAV = """    <div class="nav-group nav-doclinks">
      <h4>Documentation</h4>
      <a href="README.html">README</a>
      <a href="docs/index.html">Docs Home</a>
      <a href="docs/user-guide.html">User Guide</a>
      <a href="docs/architecture.html">Architecture</a>
      <a href="sprep/sprep-spec.html">SPREP Spec</a>
    </div>
    <div class="nav-group">
      <h4>Project</h4>
      <a href="https://github.com/HPRCFramework/hprc-framework">GitHub ↗</a>
      <a href="https://github.com/HPRCFramework/hprc-framework/issues">Issues ↗</a>
    </div>"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<link rel="stylesheet" href="{css}"/>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <a class="brand" href="docs/index.html"><span class="logo">HP</span>
      <span><span class="name">HPRC</span><br/><span class="tag">{tag}</span></span></a>
{nav}
    <div class="nav-group"><h4>Note</h4>
      <a href="#">Generated from {src} by docs/build.py</a></div>
  </aside>
  <main class="content">
{body}
    <div class="foot">Generated from <code>{src}</code> · HPRC Framework · Apache-2.0 · © 2026 Rajesh Ramani</div>
  </main>
</div>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{ startOnLoad: true, theme: "neutral" }});</script>
</body>
</html>
"""


def have_pandoc() -> bool:
    from shutil import which
    return which("pandoc") is not None


def convert(src_path: str) -> str:
    """Markdown (GitHub-flavored) -> HTML body fragment via pandoc."""
    result = subprocess.run(
        ["pandoc", "-f", "gfm", "-t", "html", src_path],
        capture_output=True, text=True, check=True,
    )
    body = result.stdout
    for old, new in LINK_REWRITES.items():
        body = body.replace(old, new)
    # Pandoc emits ```mermaid as <pre class="mermaid"><code>…</code></pre>. Mermaid
    # renders the text content of a .mermaid element, so drop the inner <code>.
    body = re.sub(
        r'<pre class="mermaid"><code>(.*?)</code></pre>',
        r'<pre class="mermaid">\1</pre>',
        body,
        flags=re.S,
    )
    return body


def build() -> None:
    if not have_pandoc():
        sys.exit("error: pandoc is required (https://pandoc.org). Install it and retry.")
    for src, dst, title in DOCS:
        src_path = os.path.join(ROOT, src)
        if not os.path.exists(src_path):
            print(f"skip {src} (not found)")
            continue
        body = convert(src_path)
        tag = title.split("—")[-1].strip() or "Docs"
        page = TEMPLATE.format(
            title=html_mod.escape(title), css=CSS_HREF, tag=html_mod.escape(tag),
            nav=NAV, body=body, src=src,
        )
        with open(os.path.join(ROOT, dst), "w", encoding="utf-8") as f:
            f.write(page)
        print(f"wrote {dst}")


if __name__ == "__main__":
    build()
