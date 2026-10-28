# -*- coding: utf-8 -*-
"""连板网 https://lianban.net/ 公开复盘摘要（RSS + 日复盘页 meta）。"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import requests

FEED_URL = "https://lianban.net/feed.xml"
BASE_URL = "https://lianban.net"
_UA = "dragon-head-lark-bot/1.0 (+https://github.com/zjgzjg/dragon-head-lark-bot)"
_RETRY = 3

_SUMMARY_RE = re.compile(
    r"涨停(\d+)家、连板(\d+)家、最高(\d+)板、跌停(\d+)家、"
    r"封板率([\d.]+)%、炸板(\d+)家。情绪([^，。]+)(?:，温度([\d.]+)°)?。"
    r"主线题材：([^。【\n]+)"
)
_MCONCL_RE = re.compile(
    r'id="mconcl"[^>]*><div class="row1"><b>[^<]*</b>([^<]+)</div>'
)


@dataclass
class LianbanSummary:
    date_iso: str
    zt: int
    lianban: int
    max_board: int
    dt: int
    seal_rate: float
    zhaban: int
    phase: str
    temp: Optional[float]
    themes: str
    one_liner: Optional[str]
    url: str
    ai_snippet: Optional[str] = None


def _get(url: str, timeout: int = 25) -> Optional[str]:
    last: Optional[Exception] = None
    for i in range(_RETRY):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:
            last = e
            if i < _RETRY - 1:
                time.sleep(1.5 * (i + 1))
    return None


def _parse_summary_text(text: str, date_iso: str, url: str) -> Optional[LianbanSummary]:
    m = _SUMMARY_RE.search(text.replace("\n", ""))
    if not m:
        return None
    temp = float(m.group(8)) if m.group(8) else None
    return LianbanSummary(
        date_iso=date_iso,
        zt=int(m.group(1)),
        lianban=int(m.group(2)),
        max_board=int(m.group(3)),
        dt=int(m.group(4)),
        seal_rate=float(m.group(5)),
        zhaban=int(m.group(6)),
        phase=m.group(7).strip(),
        temp=temp,
        themes=m.group(9).strip().rstrip("。"),
        one_liner=None,
        url=url,
    )


def _iso_from_yyyymmdd(s: str) -> str:
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def fetch_day_summary(trade_date: str) -> Optional[LianbanSummary]:
    """trade_date: YYYYMMDD 或 YYYY-MM-DD。"""
    iso = _iso_from_yyyymmdd(trade_date)
    url = f"{BASE_URL}/days/{iso}.html"
    html = _get(url)
    if not html:
        return _fetch_from_feed(iso)
    desc = None
    for pat in (
        r'<meta name="description" content="([^"]+)"',
        r'<meta property="og:description" content="([^"]+)"',
    ):
        dm = re.search(pat, html)
        if dm:
            desc = dm.group(1)
            break
    if not desc:
        return _fetch_from_feed(iso)
    sm = _parse_summary_text(desc, iso, url)
    if not sm:
        return _fetch_from_feed(iso)
    cm = _MCONCL_RE.search(html)
    if cm:
        sm.one_liner = cm.group(1).strip()
    return sm


def _fetch_from_feed(match_iso: Optional[str] = None) -> Optional[LianbanSummary]:
    raw = _get(FEED_URL)
    if not raw:
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    channel = root.find("channel")
    if channel is None:
        return None
    for item in channel.findall("item"):
        link_el = item.find("link")
        desc_el = item.find("description")
        if link_el is None or desc_el is None or not link_el.text:
            continue
        link = link_el.text.strip()
        iso_m = re.search(r"/days/(\d{4}-\d{2}-\d{2})\.html", link)
        iso = iso_m.group(1) if iso_m else ""
        if match_iso and iso != match_iso:
            continue
        body = desc_el.text or ""
        if "CDATA" in body or body.startswith("202"):
            text = re.sub(r"^.*?(\d{4}年\d+月\d+日)", r"\1", body, count=1)
        else:
            text = body
        sm = _parse_summary_text(text, iso, link)
        if sm:
            ai = re.search(r"【AI复盘】(.{0,280})", text, re.DOTALL)
            if ai:
                snip = re.sub(r"\s+", " ", ai.group(1)).strip()
                sm.ai_snippet = snip + ("…" if len(snip) >= 280 else "")
            return sm
    return None


def fetch_latest_summary() -> Optional[LianbanSummary]:
    return _fetch_from_feed(None)


def format_lianban_section(sm: LianbanSummary, *, title: str = "连板网") -> List[str]:
    temp = f"{sm.temp:.0f}°" if sm.temp is not None else "—"
    lines = [
        f"### {title}（[lianban.net]({sm.url})）",
        f"- **{sm.date_iso}** {sm.phase} **温度 {temp}** | "
        f"涨停 **{sm.zt}** 连板 **{sm.lianban}** 最高 **{sm.max_board}板** | "
        f"跌停 **{sm.dt}** 封板率 **{sm.seal_rate:.1f}%** 炸板 **{sm.zhaban}**",
        f"- 主线：**{sm.themes}**",
    ]
    if sm.one_liner:
        lines.append(f"- 结论：{sm.one_liner}")
    if sm.ai_snippet:
        lines.append(f"- AI 摘要：{sm.ai_snippet}")
    return lines


def prior_trade_date_yyyymmdd(ref: Optional[datetime] = None) -> str:
    """竞价日取上一交易日：简单跳过周末（节假日由连板网页/RSS 兜底）。"""
    ref = ref or datetime.now()
    d = ref
    for _ in range(10):
        d = d - timedelta(days=1)
        if d.weekday() < 5:
            return d.strftime("%Y%m%d")
    return (ref - timedelta(days=1)).strftime("%Y%m%d")
