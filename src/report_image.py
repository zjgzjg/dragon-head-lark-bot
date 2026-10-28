# -*- coding: utf-8 -*-
"""Markdown 复盘 → 长图（保留表格）。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import markdown

_REPORT_CSS = """
body {
  font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
  font-size: 14px;
  line-height: 1.55;
  color: #1f2329;
  background: #fff;
  margin: 0;
  padding: 20px 24px 32px;
  width: 920px;
  box-sizing: border-box;
}
h1 { font-size: 22px; margin: 0 0 12px; border-bottom: 2px solid #3370ff; padding-bottom: 8px; }
h2 { font-size: 17px; margin: 20px 0 10px; color: #245bdb; }
h3 { font-size: 15px; margin: 14px 0 8px; }
p, blockquote { margin: 8px 0; }
blockquote {
  border-left: 3px solid #ffc60a;
  padding: 6px 12px;
  background: #fffbe6;
  color: #5c4e00;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0 16px;
  font-size: 13px;
  table-layout: fixed;
  word-wrap: break-word;
}
th, td {
  border: 1px solid #dee0e3;
  padding: 8px 10px;
  vertical-align: top;
}
th { background: #f0f4ff; font-weight: 600; }
tr:nth-child(even) td { background: #fafbfc; }
code, pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  background: #f5f6f7;
  border-radius: 4px;
}
pre { padding: 10px; overflow-x: auto; white-space: pre-wrap; }
hr { border: none; border-top: 1px solid #e5e6eb; margin: 16px 0; }
strong { color: #0f1114; }
"""


def _md_to_html(md_text: str, title: str) -> str:
    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
    )
    safe_title = re.sub(r"<[^>]+>", "", title)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>{_REPORT_CSS}</style></head>
<body><h1>{safe_title}</h1>{body}</body></html>"""


def render_markdown_long_image(
    md_text: str,
    *,
    title: str,
    out_path: Optional[Path] = None,
) -> Optional[Path]:
    if os.environ.get("FEISHU_REPORT_IMAGE", "1").strip() in ("0", "false", "no"):
        return None
    out = out_path or Path(os.environ.get("REPORT_IMAGE_PATH", "report_long.png"))
    html = _md_to_html(md_text, title)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed, skip report image")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 960, "height": 900})
            page.set_content(html, wait_until="load")
            height = page.evaluate("() => document.body.scrollHeight")
            page.set_viewport_size({"width": 960, "height": min(max(height + 40, 400), 16000)})
            page.screenshot(path=str(out), full_page=True, type="png")
            browser.close()
    except Exception as exc:
        print(f"report image render failed: {exc}")
        return None
    return out if out.is_file() else None
