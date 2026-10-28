# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta


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
