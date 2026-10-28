# -*- coding: utf-8 -*-
"""竞价结束：市场 + 观察名单竞价裁决。"""
from __future__ import annotations

from datetime import datetime
from typing import List

from src.lianban_net import fetch_day_summary, format_lianban_section, prior_trade_date_yyyymmdd
from src.market_data import fetch_open_snapshot, latest_trade_date, fetch_zt_pool


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


def _fmt_snap(code: str, snap: dict) -> str:
    if snap.get("pct_open") is None:
        return f"- **{code}** 开{snap['open']:.2f} 现{snap['last']:.2f}（昨收缺失，暂不算%）"
    return (
        f"- **{code}** 开 {snap['open']:.2f} ({snap['pct_open']:+.2f}%) "
        f"现 {snap['last']:.2f} ({snap['pct_last']:+.2f}%) → {_auction_verdict(snap['pct_open'])}"
    )


def build_auction_report(watch_codes: List[str], thermometer: str) -> str:
    now = datetime.now()
    date = latest_trade_date(now)
    zt_codes: set = set()
    try:
        zt = fetch_zt_pool(date)
        zt.attrs["date"] = date
        zt_codes = set(zt["代码"].astype(str))
    except Exception:
        zt = None
        zt_codes = set()

    lines = [
        f"## ⏰ {now.strftime('%Y-%m-%d %H:%M')} 竞价快报（龙头战法）",
        "",
    ]
    if zt is None:
        lines += ["> ⚠️ 涨停池拉取失败（数据源限流），仅展示观察名单竞价。", ""]

    prev = prior_trade_date_yyyymmdd(now)
    lb = fetch_day_summary(prev)
    if lb:
        lines += format_lianban_section(lb, title="昨收·连板网环境锚")
        lines.append("")

    lines += ["### 体温计"]
    th = fetch_open_snapshot(thermometer, now)
    if th:
        lines.append(_fmt_snap(thermometer, th))
    else:
        lines.append(f"- `{thermometer}` 行情获取失败")

    lines += ["", "### 观察名单", ""]
    for code in watch_codes:
        code = code.strip()
        if not code or code == thermometer:
            continue
        snap = fetch_open_snapshot(code, now)
        in_pool = code in zt_codes
        if not snap:
            lines.append(f"- `{code}` 无数据")
            continue
        pool = "在涨停池" if in_pool else "不在池"
        if snap.get("pct_open") is None:
            lines.append(
                f"- **{code}** 开{snap['open']:.2f} 现{snap['last']:.2f} {pool}（昨收缺失）"
            )
        else:
            lines.append(
                f"- **{code}** 开{snap['pct_open']:+.2f}% 现{snap['pct_last']:+.2f}% "
                f"{pool} → {_auction_verdict(snap['pct_open'])}"
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
