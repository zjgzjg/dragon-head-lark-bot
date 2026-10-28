# -*- coding: utf-8 -*-
"""观察名单：默认按当日涨停池规则自动生成，WATCHLIST 仅作手动/合并补充。"""
from __future__ import annotations

import os
from typing import List

import pandas as pd

_CONSUMER_HINT = r"消费|零售|食品|百货|商业|餐饮|酿酒|旅游|酒店|乳业|预制菜|电商"

# 与 _hard_pass 一致，用于推送文案
HARD_CONDITIONS_TEXT = "连板≥2 · 封单比≥3% · 炸板<3 · 换手≤20% · 14:00 前首封"

THERMOMETER_ROLE_DEFAULT = "体温计·定权限（不接力）"


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


def _mainline_keyword() -> str:
    return os.environ.get("MAINLINE_KEYWORD", "").strip()


def _text_columns(df: pd.DataFrame) -> List[str]:
    preferred = ["所属行业", "涨停原因", "所属概念", "板块", "题材", "涨停统计"]
    cols = [c for c in preferred if c in df.columns]
    if cols:
        return cols
    return [
        c
        for c in df.columns
        if any(x in str(c) for x in ("行业", "原因", "概念", "板块", "题材"))
    ]


def _consumer_mask(df: pd.DataFrame) -> pd.Series:
    cols = [c for c in ["所属行业", "涨停原因", "名称"] if c in df.columns]
    if not cols:
        return pd.Series(False, index=df.index)
    text = df[cols].astype(str).agg(" ".join, axis=1)
    return text.str.contains(_CONSUMER_HINT, na=False, regex=True)


def _mainline_match_mask(df: pd.DataFrame, kw: str) -> pd.Series:
    cols = _text_columns(df)
    if not cols:
        return pd.Series(False, index=df.index)
    mask = pd.Series(False, index=df.index)
    for col in cols:
        mask |= df[col].astype(str).str.contains(kw, na=False, regex=False)
    return mask


def mainline_pool(df: pd.DataFrame) -> pd.DataFrame:
    """
    主线票集合：先按关键字扫行业/涨停原因/概念等；若无命中（东财行业常无「机器人」），
    则去掉消费支线后作为观察宇宙，避免把上海九百这类全市场高度误当机器人体温计。
    """
    if not _has_zt_pool(df):
        return pd.DataFrame()
    kw = _mainline_keyword()
    if not kw:
        return df
    matched = df[_mainline_match_mask(df, kw)]
    if not matched.empty:
        return matched
    rest = df[~_consumer_mask(df)]
    return rest if not rest.empty else df


def _mainline_filter(df: pd.DataFrame) -> pd.DataFrame:
    return mainline_pool(df)


def pick_auto_thermometer(df: pd.DataFrame) -> str:
    """
    体温计：主线宇宙里的空间龙（非全市场消费高度）。
    排序：连板最高 → 首封更早 → 封单更软（更偏情绪标，默认不当买点）。
    """
    if not _has_zt_pool(df):
        return ""
    base = mainline_pool(df)
    if base.empty:
        return ""
    if _mainline_keyword():
        h = int(base["连板数"].max())
        base = base[base["连板数"] == h]
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


def _therm_label(code: str, name: str = "") -> str:
    c = (code or "").strip()
    n = (name or "").strip()
    if n and c:
        return f"**{n}**（`{c}`）"
    return f"**{n}**" if n else (f"`{c}`" if c else "—")


def thermometer_source_note(code: str, name: str = "") -> str:
    manual = os.environ.get("THERMOMETER", "").strip()
    mode = os.environ.get("THERMOMETER_MODE", "auto").strip().lower()
    lab = _therm_label(code, name)
    if mode == "manual" or (manual and manual == code):
        return f"体温计：{lab}（手动指定）"
    if not code:
        return "体温计：涨停池缺失，未指定"
    kw = _mainline_keyword()
    hint = f"主线「{kw}」空间龙" if kw else "主线空间龙"
    return f"体温计：{lab}（{hint}·自动）"


def pick_auto_watch_codes(
    df: pd.DataFrame,
    thermometer: str,
    max_n: int = 5,
) -> List[str]:
    """从收盘涨停池按硬条件 + 主线 + 排序生成次日观察代码（不含体温计）。"""
    if not _has_zt_pool(df):
        return []
    base = mainline_pool(df)
    if base.empty:
        return []
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
    kw = _mainline_keyword()
    mainline = f" + 主线「{kw}」排序" if kw else ""
    hard = f"硬条件：{HARD_CONDITIONS_TEXT}"
    if mode == "manual":
        return "观察名单来源：**手动 WATCHLIST**"
    if mode == "merge":
        return f"观察名单来源：**{hard}{mainline}** + **WATCHLIST 补充**（`merge`）"
    return f"观察名单来源：**当日涨停池自动生成**（{hard}{mainline}，`auto`）"
