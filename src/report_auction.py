# -*- coding: utf-8 -*-
"""竞价结束：市场 + 观察名单竞价裁决。"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List

from src.market_data import fetch_open_snapshot, latest_trade_date, fetch_zt_pool, fetch_watchlist_rows


def _auction_verdict(pct_open: float) -> str:
    if pct_open <= -2:
        return "❌ 低开>2% 否决"
    if pct_open <= 0:
        return "⚠️ 低开0~2% 等10:00/承接"
    if pct_open <= 3:
        return "🟡 高开0~3% 谨慎"
    if pct_open <= 7:
        return "🟢 高开3~7% 可观察"
    return "🔴 高开>7% 透支"


def build_auction_report(watch_codes: List[str], thermometer: str) -> str:
    now = datetime.now()
    date = latest_trade_date(now)
    zt = fetch_zt_pool(date)
    zt.attrs["date"] = date

    lines = [
        f"## ⏰ {now.strftime('%Y-%m-%d %H:%M')} 竞价快报（龙头战法）",
        "",
        "### 体温计",
    ]
    th = fetch_open_snapshot(thermometer, now)
    if th:
        lines.append(
            f"- **{thermometer}** 开 {th['open']:.2f} ({th['pct_open']:+.2f}%) "
            f"现 {th['last']:.2f} ({th['pct_last']:+.2f}%) → {_auction_verdict(th['pct_open'])}"
        )
    else:
        lines.append(f"- `{thermometer}` 行情获取失败")

    lines += ["", "### 观察名单", ""]
    for code in watch_codes:
        code = code.strip()
        if not code or code == thermometer:
            continue
        snap = fetch_open_snapshot(code, now)
        in_pool = code in set(zt["代码"].astype(str))
        if not snap:
            lines.append(f"- `{code}` 无数据")
            continue
        lines.append(
            f"- **{code}** 开{snap['pct_open']:+.2f}% 现{snap['pct_last']:+.2f}% "
            f"{'在涨停池' if in_pool else '不在池'} → {_auction_verdict(snap['pct_open'])}"
        )

    lines += [
        "",
        "### 执行提醒",
        "- 竞价只否决；9:35–9:45 承接三件套才考虑动手。",
        "- 板块不同步 → 不做。",
        "",
        "> 不构成投资建议。",
    ]
    return "\n".join(lines)
