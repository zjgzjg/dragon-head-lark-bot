# -*- coding: utf-8 -*-
"""竞价结束：市场 + 观察名单竞价裁决。"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

import pandas as pd

from src.lianban_net import fetch_day_summary, format_lianban_section
from src.market_data import fetch_open_snapshot, fetch_zt_pool
from src.trade_calendar import (
    beijing_session_yyyymmdd,
    fmt_date,
    now_beijing,
    prior_trade_date_yyyymmdd,
    weekday_cn,
)
from src.watchlist import resolve_thermometer, resolve_watch_codes, thermometer_source_note, watchlist_source_note
from src.watchlist_snapshot import load_snapshot_for_session


def _norm_code(code: str) -> str:
    c = str(code).strip()
    if c.isdigit():
        return c.zfill(6)
    return c


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


def _names_from_pool(df: Optional[pd.DataFrame]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    if df is None or df.empty or "名称" not in df.columns:
        return names
    for _, row in df.iterrows():
        code = _norm_code(row["代码"])
        names[code] = str(row["名称"])
    return names


def _label(code: str, names: Dict[str, str]) -> str:
    c = _norm_code(code)
    name = names.get(c, "").strip()
    return f"**{name}**（{c}）" if name else f"**{c}**"


def _fmt_snap(code: str, snap: dict, names: Dict[str, str]) -> str:
    lab = _label(code, names)
    if snap.get("pct_open") is None:
        return (
            f"- {lab} 开{snap['open']:.2f} 现{snap['last']:.2f}（昨收缺失，暂不算%）"
        )
    return (
        f"- {lab} 开 {snap['open']:.2f} ({snap['pct_open']:+.2f}%) "
        f"现 {snap['last']:.2f} ({snap['pct_last']:+.2f}%) → {_auction_verdict(snap['pct_open'])}"
    )


def build_auction_report(watch_codes: List[str], thermometer: str) -> str:
    now_bj = now_beijing()
    session = beijing_session_yyyymmdd(now_bj)
    prev = prior_trade_date_yyyymmdd(now_bj)
    time_s = now_bj.strftime("%Y-%m-%d %H:%M")

    zt: Optional[pd.DataFrame] = None
    zt_codes: Set[str] = set()
    try:
        zt = fetch_zt_pool(prev)
        zt.attrs["date"] = prev
        zt_codes = {_norm_code(c) for c in zt["代码"].astype(str)}
    except Exception:
        zt = None
        zt_codes = set()

    pool_for_list = zt if zt is not None else pd.DataFrame()
    pool_for_list.attrs["date"] = prev
    pool_names = _names_from_pool(zt)

    snapshot = load_snapshot_for_session(session)
    snapshot_note = ""
    if snapshot:
        thermometer = (snapshot.get("thermometer") or "").strip()
        active_watch = [_norm_code(c) for c in snapshot.get("watch") or []]
        for k, v in (snapshot.get("names") or {}).items():
            pool_names[_norm_code(k)] = str(v)
        list_date = str(snapshot.get("list_date") or prev)
        snapshot_note = (
            f"> 📌 **{fmt_date(session)} 竞价名单** = {fmt_date(list_date)} 收盘定版（非重新扫池）"
        )
    else:
        list_date = prev
        thermometer = (thermometer or "").strip() or resolve_thermometer(pool_for_list)
        active_watch = [_norm_code(c) for c in resolve_watch_codes(pool_for_list, thermometer, watch_codes)]
        snapshot_note = (
            f"> ⚠️ 未找到 {fmt_date(session)} 收盘定版缓存，已按 **{fmt_date(prev)}** 涨停池临时生成"
        )

    lines = [
        f"## ⏰ {fmt_date(session)}（{weekday_cn(session)}）北京 {now_bj.strftime('%H:%M')} 竞价快报",
        "",
        f"**交易日 {fmt_date(session)}** · 昨收定名单 **{fmt_date(list_date)}** · 生成时刻 {time_s}（Asia/Shanghai）",
        "",
    ]
    if zt is None:
        lines += ["> ⚠️ 东财涨停池拉取失败（限流），竞价价仍走新浪/腾讯。", ""]

    lb = fetch_day_summary(list_date)
    if lb:
        lines += format_lianban_section(lb, title=f"{fmt_date(list_date)} 收盘·连板网环境锚")
        lines.append("")

    lines += ["### 体温计"]
    if thermometer:
        th = fetch_open_snapshot(thermometer, now_bj)
        if th:
            if th.get("name"):
                pool_names[_norm_code(thermometer)] = str(th["name"])
            lines.append(_fmt_snap(thermometer, th, pool_names))
        else:
            lines.append(f"- {_label(thermometer, pool_names)} 行情获取失败")
    else:
        lines.append("- 未选出体温计；9:25 先看观察名单里板最高的一只")

    lines += [
        "",
        snapshot_note,
        f"> {watchlist_source_note()}",
        f"> {thermometer_source_note(thermometer)}",
        "",
        "### 观察名单",
        "",
    ]
    scan: List[str] = []
    for c in active_watch:
        c = _norm_code(c)
        if c and c not in scan:
            scan.append(c)
    therm_n = _norm_code(thermometer) if thermometer else ""
    if therm_n and therm_n not in scan:
        scan.append(therm_n)

    for code in scan:
        snap = fetch_open_snapshot(code, now_bj)
        in_pool = code in zt_codes
        if snap and snap.get("name"):
            pool_names[code] = str(snap["name"])
        if not snap:
            lines.append(f"- {_label(code, pool_names)} 无数据")
            continue
        pool = "在涨停池" if in_pool else "不在池"
        if snap.get("pct_open") is None:
            lines.append(
                f"- {_label(code, pool_names)} 开{snap['open']:.2f} 现{snap['last']:.2f} {pool}（昨收缺失）"
            )
        else:
            lines.append(
                f"- {_label(code, pool_names)} 开{snap['pct_open']:+.2f}% 现{snap['pct_last']:+.2f}% "
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
