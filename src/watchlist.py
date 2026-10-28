# -*- coding: utf-8 -*-
"""观察名单：默认按当日涨停池规则自动生成，WATCHLIST 仅作手动/合并补充。"""
from __future__ import annotations

import os
from typing import List

import pandas as pd


def parse_manual_watchlist() -> List[str]:
    raw = os.environ.get("WATCHLIST", "").strip()
    if not raw:
        return []
    return [c.strip() for c in raw.split(",") if c.strip()]


def _has_zt_pool(df: pd.DataFrame) -> bool:
    return (
        df is not None
        and not df.empty
        and "连板数" in df.columns
        and "代码" in df.columns
    )


def _hard_pass(row: pd.Series) -> bool:
    return (
        row["连板数"] >= 2
        and row["封单比"] >= 3
        and row["炸板次数"] < 3
        and row["换手率"] <= 20
        and int(row["首次封板时间"]) <= 140000
    )


def _mainline_filter(df: pd.DataFrame) -> pd.DataFrame:
    kw = os.environ.get("MAINLINE_KEYWORD", "").strip()
    if not kw or df.empty:
        return df
    col = "所属行业" if "所属行业" in df.columns else None
    if col:
        return df[df[col].astype(str).str.contains(kw, na=False)]
    return df


def pick_auto_thermometer(df: pd.DataFrame) -> str:
    """
    体温计：主线（MAINLINE_KEYWORD）里当日空间龙，用来读次日竞价「权限」。
    排序：连板最高 → 首封更早 → 封单更软（更偏情绪标，默认不当买点）。
    """
    if not _has_zt_pool(df):
        return ""
    base = _mainline_filter(df)
    if base.empty:
        base = df
    if base.empty:
        return ""
    sub = base.sort_values(
        ["连板数", "首次封板时间", "封单比"],
        ascending=[False, True, True],
    )
    return str(sub.iloc[0]["代码"])


def resolve_thermometer(df: pd.DataFrame) -> str:
    """
    THERMOMETER_MODE:
    - auto（默认）：规则选主线空间龙；未填 THERMOMETER 时完全自动
    - manual：仅 THERMOMETER 环境变量
    若 auto 且设置了 THERMOMETER，视为当日手动钉住（覆盖自动）。
    """
    manual = os.environ.get("THERMOMETER", "").strip()
    mode = os.environ.get("THERMOMETER_MODE", "auto").strip().lower()
    if mode == "manual":
        return manual
    if manual:
        return manual
    return pick_auto_thermometer(df)


def thermometer_source_note(code: str) -> str:
    manual = os.environ.get("THERMOMETER", "").strip()
    mode = os.environ.get("THERMOMETER_MODE", "auto").strip().lower()
    if mode == "manual" or (manual and manual == code):
        return f"体温计：**手动 THERMOMETER**（`{code}`）"
    if not code:
        return "体温计：涨停池缺失，未指定"
    return f"体温计：**主线空间龙自动生成**（`{code}`）"


def pick_auto_watch_codes(
    df: pd.DataFrame,
    thermometer: str,
    max_n: int = 5,
) -> List[str]:
    """从收盘涨停池按硬条件 + 主线 + 排序生成次日观察代码（不含体温计）。"""
    if not _has_zt_pool(df):
        return []
    base = _mainline_filter(df)
    if base.empty:
        base = df
    sub = base[base["连板数"] >= 2].copy()
    if sub.empty:
        return []
    sub = sub.sort_values(
        ["连板数", "封单比", "炸板次数", "首次封板时间"],
        ascending=[False, False, True, True],
    )
    codes: List[str] = []
    strict = sub[sub.apply(_hard_pass, axis=1)].sort_values(
        ["封单比", "连板数", "首次封板时间"],
        ascending=[False, False, True],
    )
    for c in strict["代码"].astype(str):
        if c == thermometer or c in codes:
            continue
        codes.append(c)
        if len(codes) >= max_n - 1:
            return codes

    for c in sub["代码"].astype(str):
        if c == thermometer or c in codes:
            continue
        codes.append(c)
        if len(codes) >= max_n - 1:
            break
    return codes


def resolve_watch_codes(
    df: pd.DataFrame,
    thermometer: str,
    manual: List[str],
    max_n: int = 5,
) -> List[str]:
    """
    WATCHLIST_MODE:
    - auto（默认）：仅规则生成
    - merge：规则优先，再补 manual
    - manual：仅 WATCHLIST
    """
    mode = os.environ.get("WATCHLIST_MODE", "auto").strip().lower()
    therm = thermometer.strip()
    manual = [c.strip() for c in manual if c.strip() and c.strip() != therm]

    auto = pick_auto_watch_codes(df, therm, max_n=max_n)

    if mode == "manual":
        out = manual[: max_n - 1]
    elif mode == "merge":
        out: List[str] = []
        for c in auto + manual:
            if c not in out and c != therm:
                out.append(c)
            if len(out) >= max_n - 1:
                break
    else:
        out = auto

    if not out and manual:
        out = manual[: max_n - 1]
    return out


def watchlist_source_note() -> str:
    mode = os.environ.get("WATCHLIST_MODE", "auto").strip().lower()
    if mode == "manual":
        return "观察名单来源：**手动 WATCHLIST**"
    if mode == "merge":
        return "观察名单来源：**规则生成 + WATCHLIST 补充**（`WATCHLIST_MODE=merge`）"
    return "观察名单来源：**当日涨停池硬条件 + 主线排序自动生成**（`WATCHLIST_MODE=auto`）"
