# -*- coding: utf-8 -*-
"""A 股涨停池与观察名单行情（akshare）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import akshare as ak
import pandas as pd


@dataclass
class ZtSummary:
    date: str
    count: int
    max_height: int
    lianban_ge2: int


def _trade_date_str(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def latest_trade_date(ref: Optional[datetime] = None) -> str:
    ref = ref or datetime.now()
    for i in range(0, 10):
        d = ref - timedelta(days=i)
        s = _trade_date_str(d)
        try:
            df = ak.stock_zt_pool_em(date=s)
            if df is not None and len(df) > 0:
                return s
        except Exception:
            continue
    return _trade_date_str(ref)


def fetch_zt_pool(date: str) -> pd.DataFrame:
    df = ak.stock_zt_pool_em(date=date)
    df = df.copy()
    df["封单比"] = df["封板资金"] / df["流通市值"] * 100
    return df


def summarize_zt(df: pd.DataFrame, date: str) -> ZtSummary:
    max_h = int(df["连板数"].max()) if len(df) else 0
    ge2 = int((df["连板数"] >= 2).sum()) if len(df) else 0
    return ZtSummary(date=date, count=len(df), max_height=max_h, lianban_ge2=ge2)


def fetch_watchlist_rows(codes: List[str], zt_df: pd.DataFrame) -> List[Dict]:
    rows = []
    for code in codes:
        code = code.strip()
        if not code:
            continue
        r = zt_df[zt_df["代码"] == code]
        if len(r):
            x = r.iloc[0]
            rows.append(
                {
                    "code": code,
                    "name": x["名称"],
                    "in_zt": True,
                    "height": int(x["连板数"]),
                    "seal_ratio": float(x["封单比"]),
                    "zhaban": int(x["炸板次数"]),
                    "turnover": float(x["换手率"]),
                    "first_time": str(x["首次封板时间"]),
                    "close": float(x["最新价"]),
                }
            )
        else:
            try:
                d = zt_df.attrs.get("date") or latest_trade_date()
                h = ak.stock_zh_a_hist(
                    symbol=code, period="daily", start_date=d, end_date=d, adjust="",
                )
                if len(h):
                    x = h.iloc[-1]
                    rows.append(
                        {
                            "code": code,
                            "name": code,
                            "in_zt": False,
                            "close": float(x["收盘"]),
                            "pct": float(x["涨跌幅"]),
                        }
                    )
            except Exception:
                rows.append({"code": code, "name": code, "in_zt": False, "error": True})
    return rows


def fetch_open_snapshot(code: str, trade_date: datetime) -> Optional[Dict]:
    """当日竞价/开盘近似：日线今开 + 实时五档（失败则 None）。"""
    try:
        b = ak.stock_bid_ask_em(symbol=code)
        row = {r["item"]: r["value"] for _, r in b.iterrows()}
        return {
            "open": float(row["今开"]),
            "last": float(row["最新"]),
            "prev": float(row["昨收"]),
            "pct_open": (float(row["今开"]) / float(row["昨收"]) - 1) * 100,
            "pct_last": (float(row["最新"]) / float(row["昨收"]) - 1) * 100,
        }
    except Exception:
        sym = ("sh" if code.startswith("6") else "sz") + code
        m = ak.stock_zh_a_minute(symbol=sym, period="1", adjust="")
        m["day"] = pd.to_datetime(m["day"])
        td = m[m["day"].dt.date == trade_date.date()].sort_values("day")
        if td.empty:
            return None
        for c in ("open", "close"):
            td[c] = pd.to_numeric(td[c], errors="coerce")
        o = float(td.iloc[0]["open"])
        last = float(td.iloc[-1]["close"])
        # 昨收需另取
        h = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(trade_date - timedelta(days=10)).strftime("%Y%m%d"),
            end_date=trade_date.strftime("%Y%m%d"),
            adjust="",
        )
        prev = float(h.iloc[-2]["收盘"]) if len(h) >= 2 else float(h.iloc[-1]["收盘"])
        return {
            "open": o,
            "last": last,
            "prev": prev,
            "pct_open": (o / prev - 1) * 100,
            "pct_last": (last / prev - 1) * 100,
        }
