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


def _snap_cells(
    code: str,
    snap: Optional[dict],
    names: Dict[str, str],
    *,
    in_pool: bool = False,
    mark_therm: bool = False,
) -> tuple:
    c = _norm_code(code)
    name = names.get(c, c) + ("（体温）" if mark_therm else "")
    if not snap:
        return c, name, "—", "—", "—", "—", "无数据"
    pool = "在池" if in_pool else "不在池"
    open_txt = f"{snap['open']:.2f}"
    if snap.get("pct_open") is None:
        pct_o, pct_l, verdict = "—", "—", "—"
    else:
        pct_o = f"{snap['pct_open']:+.2f}%"
        pct_l = f"{snap['pct_last']:+.2f}%"
        verdict = _auction_verdict(float(snap["pct_open"]))
    return c, name, open_txt, pct_o, pct_l, pool, verdict


def _therm_row(code: str, snap: Optional[dict], names: Dict[str, str], in_pool: bool) -> str:
    cells = _snap_cells(code, snap, names, in_pool=in_pool, mark_therm=True)
    return "| " + " | ".join(cells) + " |"


def _watch_row(idx: int, code: str, snap: Optional[dict], names: Dict[str, str], in_pool: bool) -> str:
    c, name, _, pct_o, pct_l, pool, verdict = _snap_cells(code, snap, names, in_pool=in_pool)
    return f"| {idx} | {c} | {name} | {pct_o} | {pct_l} | {pool} | {verdict} |"


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

    lines += [
        "### 体温计",
        "",
        "| 代码 | 名称 | 开盘 | 开盘% | 现价% | 池 | 裁决 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    if thermometer:
        th = fetch_open_snapshot(thermometer, now_bj)
        if th and th.get("name"):
            pool_names[_norm_code(thermometer)] = str(th["name"])
        lines.append(
            _therm_row(
                thermometer,
                th,
                pool_names,
                _norm_code(thermometer) in zt_codes,
            )
        )
    else:
        lines.append("| — | 未选出 | — | — | — | — | — |")

    lines += [
        "",
        snapshot_note,
        f"> {watchlist_source_note()}",
        f"> {thermometer_source_note(thermometer, pool_names.get(_norm_code(thermometer), ''))}",
        "",
        "### 观察名单",
        "",
        "| # | 代码 | 名称 | 开盘% | 现价% | 池 | 裁决 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    scan: List[str] = []
    for c in active_watch:
        c = _norm_code(c)
        if c and c not in scan:
            scan.append(c)
    therm_n = _norm_code(thermometer) if thermometer else ""
    if therm_n and therm_n not in scan:
        scan.append(therm_n)

    idx = 0
    for code in scan:
        if code == therm_n:
            continue
        idx += 1
        snap = fetch_open_snapshot(code, now_bj)
        if snap and snap.get("name"):
            pool_names[code] = str(snap["name"])
        lines.append(_watch_row(idx, code, snap, pool_names, code in zt_codes))

    lines += [
        "",
        "### 执行提醒",
        "- 竞价只否决；9:35–9:45 承接三件套才考虑动手。",
        "- 板块不同步 → 不做。",
        "",
        "> 不构成投资建议。",
    ]
    return "\n".join(lines)
