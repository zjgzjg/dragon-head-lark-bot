# -*- coding: utf-8 -*-
"""收盘：全市场摘要 + 次日观察名单（规则+数据，可选 LLM）。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

import pandas as pd

from src.market_data import (
    fetch_watchlist_rows,
    fetch_zt_pool,
    latest_trade_date,
    summarize_zt,
)


def _hard_pass(row: pd.Series) -> bool:
    return (
        row["连板数"] >= 2
        and row["封单比"] >= 3
        and row["炸板次数"] < 3
        and row["换手率"] <= 20
        and int(row["首次封板时间"]) <= 140000
    )


def pick_watchlist(df: pd.DataFrame, max_n: int = 5) -> pd.DataFrame:
    sub = df[df["连板数"] >= 2].copy()
    sub = sub.sort_values(["连板数", "首次封板时间"], ascending=[False, True])
    strict = sub[sub.apply(_hard_pass, axis=1)]
    if len(strict) >= 2:
        return strict.head(max_n)
    return sub.head(max_n)


def build_close_report(date: str, watch_codes: List[str], thermometer: str) -> str:
    df = fetch_zt_pool(date)
    df.attrs["date"] = date
    sm = summarize_zt(df, date)

    watch = pick_watchlist(df)
    watch_rows = fetch_watchlist_rows(watch_codes, df)

    lines = [
        f"## 📊 {date[:4]}-{date[4:6]}-{date[6:8]} 收盘复盘（龙头战法）",
        "",
        "### 环境",
        f"- 涨停 **{sm.count}** 家 | 连板≥2 **{sm.lianban_ge2}** 家 | 最高 **{sm.max_height}** 板",
        "",
        "### 规则内优选（硬条件过关，最多5）",
    ]
    if watch.empty:
        lines.append("- （无连板≥2 或数据为空）")
    else:
        for _, r in watch.iterrows():
            lines.append(
                f"- **{r['名称']}** `{r['代码']}` {int(r['连板数'])}板 "
                f"首封{r['首次封板时间']} 封单{r['封单比']:.1f}% 炸{r['炸板次数']} 换{r['换手率']:.1f}%"
            )

    lines += ["", "### 你的观察池", ""]
    for w in watch_rows:
        if w.get("in_zt"):
            lines.append(
                f"- **{w['name']}** {w['height']}板 收{w['close']:.2f} "
                f"封{w['seal_ratio']:.1f}% 炸{w['zhaban']}"
            )
        elif w.get("pct") is not None:
            lines.append(f"- **{w.get('name', w['code'])}** 收{w['close']:.2f} ({w['pct']:+.2f}%) 未涨停")
        else:
            lines.append(f"- `{w['code']}` 数据缺失")

    lines += [
        "",
        f"### 体温计 `{thermometer}`",
        "- 次日 9:25 只看竞价：低开>2% 关闭权限；一字只定性不买。",
        "",
        "> 方法论复盘，不构成投资建议。",
    ]
    return "\n".join(lines)


def maybe_llm_polish(text: str) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return text
    try:
        from openai import OpenAI

        snippet = Path(__file__).resolve().parents[1] / "config" / "methodology_snippet.md"
        method = snippet.read_text(encoding="utf-8") if snippet.exists() else ""
        client = OpenAI(
            api_key=key,
            base_url=os.environ.get("OPENAI_BASE_URL") or None,
        )
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "你是 A 股短线复盘助手，按用户龙头战法输出，保留数据数字不改造。",
                },
                {"role": "user", "content": f"{method}\n\n请润色以下收盘复盘并补充次日观察名单与触发/止损要点：\n\n{text}"},
            ],
            temperature=0.3,
        )
        return resp.choices[0].message.content or text
    except Exception:
        return text
