# -*- coding: utf-8 -*-
"""A 股涨停池与观察名单行情（akshare，含重试与新浪备用源）。"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, TypeVar

import akshare as ak
import pandas as pd
import requests

T = TypeVar("T")

_RETRY = 4
_RETRY_SLEEP = 2.5
_SINA_HEADERS = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}


def _is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("SKIP_EM_QUOTES") == "1"


def _retry_count(*, em_pool: bool = False) -> int:
    if em_pool and _is_ci():
        return 3
    return 1 if _is_ci() else _RETRY


def _retry_call(fn: Callable[..., T], *args, em_pool: bool = False, **kwargs) -> T:
    last: Optional[BaseException] = None
    for attempt in range(_retry_count(em_pool=em_pool)):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last = e
            if attempt < _retry_count(em_pool=em_pool) - 1:
                time.sleep(_RETRY_SLEEP * (attempt + 1))
    assert last is not None
    raise last


def _sina_symbol(code: str) -> str:
    return ("sh" if code.startswith("6") else "sz") + code.strip()


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
    try:
        from src.lianban_net import fetch_latest_summary

        lb = fetch_latest_summary()
        if lb and lb.date_iso:
            return lb.date_iso.replace("-", "")
    except Exception:
        pass
    for i in range(0, 10):
        d = ref - timedelta(days=i)
        s = _trade_date_str(d)
        try:
            df = _retry_call(ak.stock_zt_pool_em, date=s)
            if df is not None and len(df) > 0:
                return s
        except Exception:
            continue
    return _last_weekday_yyyymmdd(ref)


def _last_weekday_yyyymmdd(ref: datetime) -> str:
    d = ref
    for _ in range(10):
        if d.weekday() < 5:
            return _trade_date_str(d)
        d -= timedelta(days=1)
    return _trade_date_str(ref)


def fetch_zt_pool(date: str) -> pd.DataFrame:
    df = _retry_call(ak.stock_zt_pool_em, date=date, em_pool=True)
    df = df.copy()
    df["封单比"] = df["封板资金"] / df["流通市值"] * 100
    return df


def summarize_zt(df: pd.DataFrame, date: str) -> ZtSummary:
    max_h = int(df["连板数"].max()) if len(df) else 0
    ge2 = int((df["连板数"] >= 2).sum()) if len(df) else 0
    return ZtSummary(date=date, count=len(df), max_height=max_h, lianban_ge2=ge2)


def _prev_close(code: str, ref: datetime) -> Optional[float]:
    """昨收：优先新浪日线（Actions 上东财 hist 易断），再试东财 hist。"""
    sym = _sina_symbol(code)
    start = (ref - timedelta(days=25)).strftime("%Y%m%d")
    end = ref.strftime("%Y%m%d")
    ref_date = ref.date()
    try:
        h = _retry_call(
            ak.stock_zh_a_daily,
            symbol=sym,
            start_date=start,
            end_date=end,
            adjust="",
        )
        if h is not None and len(h):
            h = h.copy()
            h["date"] = pd.to_datetime(h["date"])
            past = h[h["date"].dt.date < ref_date]
            if len(past):
                return float(past.iloc[-1]["close"])
            return float(h.iloc[-1]["close"])
    except Exception:
        pass
    if not _is_ci():
        try:
            h = _retry_call(
                ak.stock_zh_a_hist,
                symbol=code.strip(),
                period="daily",
                start_date=start,
                end_date=end,
                adjust="",
            )
            if h is not None and len(h):
                if len(h) >= 2:
                    return float(h.iloc[-2]["收盘"])
                return float(h.iloc[-1]["收盘"])
        except Exception:
            pass
    return None


def _sina_hq_parts(code: str) -> Optional[List[str]]:
    sym = _sina_symbol(code)
    try:
        r = requests.get(
            f"https://hq.sinajs.cn/list={sym}",
            headers=_SINA_HEADERS,
            timeout=12,
        )
        r.encoding = "gbk"
        m = re.search(r'="([^"]+)"', r.text)
        if not m or not m.group(1):
            return None
        return m.group(1).split(",")
    except Exception:
        return None


def _parse_sina_hq_line(raw: str, code: str) -> Optional[Dict]:
    m = re.search(r'="([^"]+)"', raw)
    if not m:
        return None
    parts = m.group(1).split(",")
    if len(parts) < 4 or not parts[0]:
        return None
    try:
        open_p = float(parts[1])
        prev = float(parts[2])
        last = float(parts[3])
    except ValueError:
        return None
    if prev <= 0:
        return None
    if open_p <= 0:
        open_p = last
    if last <= 0:
        last = open_p
    return {
        "open": open_p,
        "last": last,
        "prev": prev,
        "pct_open": (open_p / prev - 1) * 100,
        "pct_last": (last / prev - 1) * 100,
    }


def _fetch_sina_spot(code: str) -> Optional[Dict]:
    try:
        parts = _sina_hq_parts(code)
        if not parts or len(parts) < 4:
            return None
        prev = float(parts[2])
        open_p = float(parts[1]) if parts[1] else float(parts[3])
        last = float(parts[3])
        if prev <= 0:
            return None
        if open_p <= 0:
            open_p = last
        return {
            "name": parts[0],
            "open": open_p,
            "last": last,
            "prev": prev,
            "pct_open": (open_p / prev - 1) * 100,
            "pct_last": (last / prev - 1) * 100,
        }
    except Exception:
        return None


def fetch_code_quote(code: str, trade_date: str) -> Dict:
    """单票：新浪日线（不晚于 trade_date 的最后一根），再实时行情。"""
    code = code.strip()
    sym = _sina_symbol(code)
    parts = _sina_hq_parts(code)
    name = parts[0] if parts else code
    end = trade_date
    start = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=45)).strftime("%Y%m%d")
    try:
        h = _retry_call(
            ak.stock_zh_a_daily, symbol=sym, start_date=start, end_date=end, adjust=""
        )
        if h is not None and len(h):
            h = h.copy()
            h["date"] = pd.to_datetime(h["date"])
            target = datetime.strptime(trade_date, "%Y%m%d").date()
            past = h[h["date"].dt.date <= target].sort_values("date")
            if len(past):
                x = past.iloc[-1]
                close = float(x["close"])
                pct = 0.0
                if len(past) >= 2:
                    pct = (close / float(past.iloc[-2]["close"]) - 1) * 100
                if name == code:
                    p2 = _sina_hq_parts(code)
                    if p2 and p2[0]:
                        name = p2[0]
                return {
                    "code": code,
                    "name": name,
                    "close": close,
                    "pct": pct,
                    "in_zt": False,
                    "date": past.iloc[-1]["date"].strftime("%Y%m%d"),
                }
    except Exception:
        pass
    spot = _fetch_sina_spot(code) or _fetch_tencent_spot(code)
    if spot:
        return {
            "code": code,
            "name": spot.get("name") or name,
            "close": float(spot["last"]),
            "pct": float(spot.get("pct_last") or 0),
            "in_zt": False,
        }
    return {"code": code, "name": name, "error": True}


def _fetch_tencent_spot(code: str) -> Optional[Dict]:
    sym = _sina_symbol(code)
    try:
        r = requests.get(
            f"https://qt.gtimg.cn/q={sym}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        r.encoding = "gbk"
        m = re.search(r'="([^"]+)"', r.text)
        if not m:
            return None
        parts = m.group(1).split("~")
        if len(parts) < 5:
            return None
        last = float(parts[3])
        prev = float(parts[4])
        open_p = float(parts[5]) if len(parts) > 5 and parts[5] else last
        if prev <= 0:
            return None
        if open_p <= 0:
            open_p = last
        return {
            "open": open_p,
            "last": last,
            "prev": prev,
            "pct_open": (open_p / prev - 1) * 100,
            "pct_last": (last / prev - 1) * 100,
        }
    except Exception:
        return None


def _snapshot_from_sina_minute(code: str, trade_date: datetime) -> Optional[Dict]:
    sym = _sina_symbol(code)
    m = _retry_call(ak.stock_zh_a_minute, symbol=sym, period="1", adjust="")
    m = m.copy()
    m["day"] = pd.to_datetime(m["day"])
    td = m[m["day"].dt.date == trade_date.date()].sort_values("day")
    if td.empty:
        return None
    for c in ("open", "close"):
        td[c] = pd.to_numeric(td[c], errors="coerce")
    o = float(td.iloc[0]["open"])
    last = float(td.iloc[-1]["close"])
    prev = _prev_close(code, trade_date)
    if prev is None or prev <= 0:
        return {"open": o, "last": last, "prev": None, "pct_open": None, "pct_last": None}
    return {
        "open": o,
        "last": last,
        "prev": prev,
        "pct_open": (o / prev - 1) * 100,
        "pct_last": (last / prev - 1) * 100,
    }


def fetch_open_snapshot(code: str, trade_date: datetime) -> Optional[Dict]:
    """当日竞价/开盘：新浪/腾讯实时 →（非 CI）东财五档 → 新浪分时。"""
    code = code.strip()
    for fn in (_fetch_sina_spot, _fetch_tencent_spot):
        snap = fn(code)
        if snap:
            return snap
    if not _is_ci():
        try:
            b = _retry_call(ak.stock_bid_ask_em, symbol=code)
            row = {r["item"]: r["value"] for _, r in b.iterrows()}
            prev = float(row["昨收"])
            return {
                "open": float(row["今开"]),
                "last": float(row["最新"]),
                "prev": prev,
                "pct_open": (float(row["今开"]) / prev - 1) * 100,
                "pct_last": (float(row["最新"]) / prev - 1) * 100,
            }
        except Exception:
            pass
    try:
        return _snapshot_from_sina_minute(code, trade_date)
    except Exception:
        return None


def fetch_watchlist_rows(codes: List[str], zt_df: pd.DataFrame) -> List[Dict]:
    rows = []
    pool_ok = (
        zt_df is not None
        and not zt_df.empty
        and "代码" in zt_df.columns
    )
    for code in codes:
        code = code.strip()
        if not code:
            continue
        r = zt_df[zt_df["代码"] == code] if pool_ok else pd.DataFrame()
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
            d = zt_df.attrs.get("date") or latest_trade_date()
            q = fetch_code_quote(code, d)
            if not q.get("error"):
                rows.append(
                    {
                        "code": code,
                        "name": q.get("name", code),
                        "in_zt": False,
                        "close": float(q["close"]),
                        "pct": float(q.get("pct", 0)),
                    }
                )
            else:
                rows.append({"code": code, "name": q.get("name", code), "in_zt": False, "error": True})
    return rows
