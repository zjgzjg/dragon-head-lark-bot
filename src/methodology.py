# -*- coding: utf-8 -*-
"""龙头战法方法论：与 config/methodology_snippet.md 同步，供复盘/竞价 bot 共用。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

import pandas as pd

# --- 文案（推送里展示，与 snippet 一致）---

PREMISE_LINES = [
    "冰点：空仓或只处理存量",
    "溢价弱、炸板率高：半仓，只做龙一",
    "修复/主升：方可正常接力",
]

CLOSE_STEPS = [
    "定主线：东财概念涨停家数 + 成交前排集中度 × 连板网主线交叉确认",
    "认龙头：首封 一字 > 秒板 > 早板 > 尾盘",
    "看位置：最高板是否还在、中间是否断层",
    "验筹码：封单≥3%；一字低换手；分歧板高换手",
]

CLOSE_HARD_LINE = "硬条件：连板≥2、封单≥3%、炸板<3、换手≤20%、在主线板块"

CLOSE_VETO_MANUAL = [
    "龙二心理（非龙一不接力）",
    "高开>2%追（次日竞价不追）",
    "补涨（低位跟风）",
    "14:00 后首封",
    "炸板≥3",
]

AUCTION_RULES = [
    "低开>2% → 从名单删",
    "竞价量>昨全天 5% 且 9:20–9:25 价跌 → 出货否决",
    "9:30–9:40：不破开、放量、板块同步",
    "买点窗口：9:35–9:45（竞价只否决、不买）",
]

THERMOMETER_RULES = [
    "一字/强开 = 线活",
    "开板 15 分钟内回封 = 唯一分歧窗",
    "不回封 = 全线撤退",
]

_CATCH_UP_HINT = re.compile(r"补涨|跟风|反弹|首板")
_DRAGON2_MAX_GAP = 1  # 比空间龙低超过 1 板且非体温 → 龙二心理


def close_hard_fail_reasons(row: pd.Series) -> List[str]:
    rs: List[str] = []
    if int(row["连板数"]) < 2:
        rs.append("连板不足 2 天")
    seal = float(row["封单比"])
    if seal < 3:
        rs.append(f"封板偏软（封单比 {seal:.1f}%，要求 ≥3%）")
    z = int(row["炸板次数"])
    if z >= 3:
        rs.append(f"炸板过多（{z} 次，否决线 ≥3）")
    turn = float(row["换手率"])
    if turn > 20:
        rs.append(f"换手偏高（{turn:.1f}%，要求 ≤20%）")
    if int(row["首次封板时间"]) > 140000:
        rs.append("首封偏晚（14:00 后，方法论否决）")
    return rs


def _text_field(row: pd.Series, *keys: str) -> str:
    for k in keys:
        if k in row.index:
            v = str(row.get(k, "")).strip()
            if v and v != "nan":
                return v
    return ""


def close_context_vetoes(
    row: pd.Series,
    *,
    max_height_in_pool: int,
    is_thermometer: bool,
) -> List[str]:
    """收盘名单语境下的方法论否决（硬条件之外的标签）。"""
    if is_thermometer:
        return []
    rs: List[str] = []
    h = int(row["连板数"])
    if max_height_in_pool > 0 and h < max_height_in_pool - _DRAGON2_MAX_GAP:
        rs.append("龙二心理（高度明显低于空间龙）")
    blob = _text_field(row, "涨停原因", "所属概念", "名称")
    if _CATCH_UP_HINT.search(blob):
        rs.append("补涨/跟风属性（方法论否决）")
    return rs


def format_close_methodology_block() -> List[str]:
    lines = ["", "### 方法论·收盘", "", "**大前提（仓位）**"]
    lines += [f"- {x}" for x in PREMISE_LINES]
    lines += ["", "**四步**"]
    lines += [f"{i + 1}. {s}" for i, s in enumerate(CLOSE_STEPS)]
    lines += ["", f"**{CLOSE_HARD_LINE}**", "", "**否决清单**"]
    lines += [f"- {x}" for x in CLOSE_VETO_MANUAL]
    return lines


def format_auction_methodology_block() -> List[str]:
    lines = ["", "### 方法论·竞价", ""]
    lines += [f"- {x}" for x in AUCTION_RULES]
    lines += ["", "**体温计**"]
    lines += [f"- {x}" for x in THERMOMETER_RULES]
    return lines


def _limit_up_pct(code: str) -> float:
    if str(code).startswith(("300", "301", "688")):
        return 20.0
    return 10.0


def auction_open_verdict(
    pct_open: float,
    *,
    dump_risk: bool = False,
    data_missing: bool = False,
) -> str:
    """竞价开盘裁决（方法论同步）。"""
    parts: List[str] = []
    if dump_risk:
        parts.append("❌ 竞价出货（量>昨5%且9:20–9:25价跌）")
    if pct_open <= -2:
        parts.append("❌ 低开>2% 删")
    elif pct_open <= 0:
        parts.append("⚠️ 低开0~2% 等10:00/承接")
    elif pct_open <= 2:
        parts.append("🟡 平开~小幅高开 可观察")
    elif pct_open <= 7:
        parts.append("❌ 高开>2% 不追")
    else:
        parts.append("🔴 高开>7% 透支")
    if data_missing and not dump_risk:
        parts.append("（量价比未验）")
    return " · ".join(parts) if parts else "—"


def thermometer_auction_verdict(pct_open: float, code: str) -> str:
    """体温计专用：线活 / 撤退权限。"""
    lim = _limit_up_pct(code)
    base = auction_open_verdict(pct_open, dump_risk=False, data_missing=False)
    if pct_open >= lim - 0.5:
        return f"{base} · **线活**（一字/近涨停开）"
    if pct_open <= -2:
        return f"{base} · **关闭接力**（低开破线）"
    if pct_open > 7:
        return f"{base} · 强但勿追价"
    return f"{base} · 9:25 定权限"


def merge_close_note(
    hard_reasons: Sequence[str],
    context_vetoes: Sequence[str],
    *,
    best_seal_note: str = "",
) -> str:
    all_r = list(hard_reasons) + list(context_vetoes)
    if not all_r:
        return best_seal_note or "硬条件全部满足"
    return "；".join(all_r)
