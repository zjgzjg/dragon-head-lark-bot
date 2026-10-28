# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

_BJ = ZoneInfo("Asia/Shanghai")


def weekday_cn(yyyymmdd: str) -> str:
    wd = datetime.strptime(yyyymmdd, "%Y%m%d").weekday()
    return f"周{'一二三四五六日'[wd]}"


def prev_trade_date(yyyymmdd: str) -> str:
    d = datetime.strptime(yyyymmdd, "%Y%m%d")
    for _ in range(1, 15):
        d -= timedelta(days=1)
        if d.weekday() < 5:
            return d.strftime("%Y%m%d")
    return yyyymmdd


def next_trade_date(yyyymmdd: str) -> str:
    d = datetime.strptime(yyyymmdd, "%Y%m%d")
    for _ in range(1, 15):
        d += timedelta(days=1)
        if d.weekday() < 5:
            return d.strftime("%Y%m%d")
    return yyyymmdd


def fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def now_beijing() -> datetime:
    return datetime.now(_BJ)


def beijing_session_yyyymmdd(ref: Optional[datetime] = None) -> str:
    """北京时间当前所属 A 股交易日（周末回退到最近周五）。"""
    ref = ref or now_beijing()
    d = ref.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def prior_trade_date_yyyymmdd(ref: Optional[datetime] = None) -> str:
    """竞价/开盘语境：上一交易日（按 **北京时间** 日历）。"""
    session = beijing_session_yyyymmdd(ref)
    return prev_trade_date(session)
