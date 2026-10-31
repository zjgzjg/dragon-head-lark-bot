# -*- coding: utf-8 -*-
"""竞价结束：市场 + 观察名单竞价裁决。"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

import pandas as pd

from src.lianban_net import fetch_day_summary, format_lianban_section
from src.market_data import fetch_auction_dump_risk, fetch_open_snapshot, fetch_zt_pool
from src.methodology import (
    auction_open_verdict,
    format_auction_methodology_block,
    thermometer_auction_verdict,
)
from src.trade_calendar import (
    beijing_session_yyyymmdd,
    fmt_date,
    now_beijing,
    prior_trade_date_yyyymmdd,
    weekday_cn,
)
from src.mainline import detect_mainline, mainline_source_note
from src.watchlist import resolve_thermometer, resolve_watch_codes, thermometer_source_note, watchlist_source_note
from src.watchlist_snapshot import load_snapshot_for_session


def _norm_code(code: str) -> str:
    c = str(code).strip()
    if c.isdigit():
        return c.zfill(6)
    return c


def _names_from_pool(df: Optional[pd.DataFrame]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    if df is None or df.empty or "名称" not in df.columns:
        return names
    for _, row in df.iterrows():
        code = _norm_code(row["代码"])
        names[code] = str(row["名称"])
    return names


def _auction_verdict_for_code(
    code: str,
    snap: Optional[dict],
    *,
    is_thermometer: bool,
    prev_date: str,
    now_bj,
) -> str:
    if not snap or snap.get("pct_open") is None:
        return "无数据"
    pct = float(snap["pct_open"])
    dump, missing = fetch_auction_dump_risk(code, now_bj, prev_date)
    if is_thermometer:
        return thermometer_auction_verdict(pct, code)
    return auction_open_verdict(pct, dump_risk=dump, data_missing=missing)


def _snap_cells(
    code: str,
    snap: Optional[dict],
    names: Dict[str, str],
    *,
    in_pool: bool = False,
    mark_therm: bool = False,
    prev_date: str = "",
    now_bj=None,
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
        verdict = _auction_verdict_for_code(
            c,
            snap,
            is_thermometer=mark_therm,
            prev_date=prev_date,
            now_bj=now_bj,
        )
    return c, name, open_txt, pct_o, pct_l, pool, verdict


def _therm_row(
    code: str,
    snap: Optional[dict],
    names: Dict[str, str],
    in_pool: bool,
    prev_date: str,
    now_bj,
) -> str:
    cells = _snap_cells(
        code,
        snap,
        names,
        in_pool=in_pool,
        mark_therm=True,
        prev_date=prev_date,
        now_bj=now_bj,
    )
    return "| " + " | ".join(cells) + " |"


def _watch_row(
    idx: int,
    code: str,
    snap: Optional[dict],
    names: Dict[str, str],
    in_pool: bool,
    prev_date: str,
    now_bj,
) -> str:
    c, name, _, pct_o, pct_l, pool, verdict = _snap_cells(
        code,
        snap,
        names,
        in_pool=in_pool,
        prev_date=prev_date,
        now_bj=now_bj,
    )
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
        active_watch = []
        snapshot_note = (
            f"> ⚠️ 未找到 {fmt_date(session)} 收盘定版缓存，已按 **{fmt_date(prev)}** 涨停池临时生成"
        )

    lb_list = fetch_day_summary(list_date)
    ml = detect_mainline(pool_for_list, lb_list)
    if not snapshot:
        thermometer = (thermometer or "").strip() or resolve_thermometer(
            pool_for_list, decision=ml
        )
        active_watch = [
            _norm_code(c)
            for c in resolve_watch_codes(
                pool_for_list, thermometer, watch_codes, decision=ml
            )
        ]

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
                prev,
                now_bj,
            )
        )
    else:
        lines.append("| — | 未选出 | — | — | — | — | — |")

    lines += [
        "",
        snapshot_note,
        f"> {mainline_source_note(ml)}",
        f"> {watchlist_source_note(ml)}",
        f"> {thermometer_source_note(thermometer, pool_names.get(_norm_code(thermometer), ''), ml)}",
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
        lines.append(
            _watch_row(idx, code, snap, pool_names, code in zt_codes, prev, now_bj)
        )

    lines += format_auction_methodology_block()
    lines += [
        "",
        "### 执行提醒",
        "- **9:30–9:40**：不破开、放量、板块同步（名单内至少 2 只站在开盘价之上）。",
        "- **9:35–9:45**：唯一可下单窗口；体温计不回封 → 全线撤退。",
        "",
        "> 不构成投资建议。",
    ]
    return "\n".join(lines)
