# -*- coding: utf-8 -*-
"""定主线：东财涨停池概念统计 + 连板网主线题材交叉确认。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.lianban_net import LianbanSummary

_TAG_SPLIT = re.compile(r"[,，、+;；/|]")
_STRIP_SUFFIX = re.compile(r"(概念|板块|题材|产业链|指数|相关)$")


@dataclass
class MainlineDecision:
    """当日主线结论（用于筛票与推送文案）。"""

    label: str
    em_leader: str
    em_count: int
    em_concentration: float
    lb_themes: List[str] = field(default_factory=list)
    confirmed: bool = False
    match_terms: List[str] = field(default_factory=list)
    detail: str = ""

    @property
    def pool_count(self) -> int:
        return self.em_count


def _normalize_tag(raw: str) -> str:
    s = str(raw).strip()
    s = _STRIP_SUFFIX.sub("", s)
    return s.strip()


def _theme_related(a: str, b: str) -> bool:
    na, nb = _normalize_tag(a), _normalize_tag(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    if len(na) >= 2 and len(nb) >= 2 and (na[:2] == nb[:2] or na[-2:] == nb[-2:]):
        return na[:2] == nb[:2]
    return False


def _text_columns(df: pd.DataFrame) -> List[str]:
    preferred = ["所属概念", "涨停原因", "涨停统计", "板块", "题材", "所属行业"]
    cols = [c for c in preferred if c in df.columns]
    if cols:
        return cols
    return [
        c
        for c in df.columns
        if any(x in str(c) for x in ("行业", "原因", "概念", "板块", "题材"))
    ]


def _row_tags(row: pd.Series, cols: List[str]) -> List[str]:
    tags: List[str] = []
    for col in cols:
        val = str(row.get(col, "")).strip()
        if not val or val == "nan":
            continue
        for part in _TAG_SPLIT.split(val):
            part = part.strip()
            if len(part) >= 2:
                tags.append(part)
    if "所属行业" in row.index:
        ind = str(row["所属行业"]).strip()
        if ind and ind != "nan":
            tags.append(ind)
    out: List[str] = []
    seen = set()
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _row_amount(row: pd.Series) -> float:
    if "成交额" in row.index:
        try:
            v = float(row["成交额"])
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    try:
        cap = float(row.get("流通市值", 0) or 0)
        turn = float(row.get("换手率", 0) or 0)
        if cap > 0 and turn > 0:
            return cap * turn / 100.0
    except (TypeError, ValueError):
        pass
    try:
        return float(row.get("封板资金", 0) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def _concentration(amounts: List[float]) -> float:
    if not amounts:
        return 0.0
    total = sum(amounts)
    if total <= 0:
        return 0.0
    top = sorted(amounts, reverse=True)[:3]
    return sum(top) / total * 100.0


def _aggregate_em_concepts(df: pd.DataFrame) -> List[Tuple[str, int, float, float]]:
    """返回 [(标签, 涨停家数, 成交额合计, 前排集中度%), ...] 按家数、集中度排序。"""
    cols = _text_columns(df)
    if not cols:
        return []
    bucket: Dict[str, List[float]] = {}
    for _, row in df.iterrows():
        amt = _row_amount(row)
        for tag in _row_tags(row, cols):
            bucket.setdefault(tag, []).append(amt)
    stats: List[Tuple[str, int, float, float]] = []
    for tag, amounts in bucket.items():
        stats.append((tag, len(amounts), sum(amounts), _concentration(amounts)))
    stats.sort(key=lambda x: (x[1], x[3], x[2]), reverse=True)
    return stats


def parse_lianban_themes(themes: str) -> List[str]:
    if not themes or not str(themes).strip():
        return []
    parts = re.split(r"[、,，/|]", str(themes))
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if len(p) >= 2:
            out.append(p)
    return out


def _match_terms_from(label: str, extras: List[str]) -> List[str]:
    terms: List[str] = []
    seen = set()
    for raw in [label] + extras:
        for piece in [raw, _normalize_tag(raw)]:
            piece = piece.strip()
            if len(piece) >= 2 and piece not in seen:
                seen.add(piece)
                terms.append(piece)
    return terms


def detect_mainline(
    df: pd.DataFrame,
    lb: Optional[LianbanSummary] = None,
) -> MainlineDecision:
    """
    涨停家数最多 + 成交额前排集中度（东财）× 连板网「主线题材」交叉确认。
    环境变量 MAINLINE_KEYWORD 非空时：强制该关键字为主线（跳过双源，便于钉题材）。
    """
    pin = os.environ.get("MAINLINE_KEYWORD", "").strip()
    lb_themes = parse_lianban_themes(lb.themes) if lb and lb.themes else []

    if df is None or df.empty or "代码" not in df.columns:
        label = pin or (lb_themes[0] if lb_themes else "—")
        return MainlineDecision(
            label=label,
            em_leader="—",
            em_count=0,
            em_concentration=0.0,
            lb_themes=lb_themes,
            confirmed=bool(pin and lb_themes and any(_theme_related(pin, t) for t in lb_themes)),
            match_terms=_match_terms_from(label, lb_themes if not pin else [pin]),
            detail="无涨停池，仅连板网/手动关键字" if not pin else f"手动主线「{pin}」",
        )

    ranked = _aggregate_em_concepts(df)
    if not ranked:
        label = pin or (lb_themes[0] if lb_themes else "—")
        return MainlineDecision(
            label=label,
            em_leader="—",
            em_count=0,
            em_concentration=0.0,
            lb_themes=lb_themes,
            match_terms=_match_terms_from(label, [pin] if pin else lb_themes),
            detail="涨停池无可用概念字段",
        )

    if pin:
        em_leader, em_n, em_c = ranked[0][0], ranked[0][1], ranked[0][3]
        confirmed = bool(lb_themes and any(_theme_related(pin, t) for t in lb_themes))
        detail = f"手动「{pin}」"
        if lb_themes:
            detail += "；与连板网一致" if confirmed else f"；连板网偏「{'、'.join(lb_themes[:2])}」"
        return MainlineDecision(
            label=pin,
            em_leader=em_leader,
            em_count=em_n,
            em_concentration=em_c,
            lb_themes=lb_themes,
            confirmed=confirmed,
            match_terms=_match_terms_from(pin, [pin]),
            detail=detail,
        )

    em_leader, em_n, _, em_conc = ranked[0]
    lb_pick = lb_themes[0] if lb_themes else ""
    confirmed = False
    label = em_leader
    if lb_themes:
        for em_tag, cnt, _, conc in ranked[:8]:
            for lt in lb_themes:
                if _theme_related(em_tag, lt):
                    label = em_tag
                    lb_pick = lt
                    em_leader, em_n, em_conc = em_tag, cnt, conc
                    confirmed = True
                    break
            if confirmed:
                break
    if not confirmed and lb_themes:
        label = em_leader
        detail = (
            f"东财最强「{em_leader}」{em_n}家·前排成交占比{em_conc:.0f}%；"
            f"连板网「{'、'.join(lb_themes[:2])}」— **待观察是否收敛**"
        )
    elif confirmed:
        detail = (
            f"东财「{em_leader}」{em_n}家·前排占比{em_conc:.0f}% "
            f"× 连板网「{lb_pick}」**一致**"
        )
    else:
        detail = f"东财「{em_leader}」{em_n}家·前排成交占比{em_conc:.0f}%（无连板网对照）"

    match_terms = _match_terms_from(label, [em_leader, lb_pick] + lb_themes[:2])
    return MainlineDecision(
        label=label,
        em_leader=em_leader,
        em_count=em_n,
        em_concentration=em_conc,
        lb_themes=lb_themes,
        confirmed=confirmed,
        match_terms=match_terms,
        detail=detail,
    )


def format_mainline_cell(
    decision: MainlineDecision,
    pool_count: int,
    lb: Optional[LianbanSummary] = None,
) -> str:
    cnt = pool_count
    flag = "**双源确认**" if decision.confirmed else "**单源/待收敛**"
    tail = ""
    if lb and lb.phase and "冰点" in lb.phase:
        tail = "，但 **缩圈抱团**"
    return f"**{decision.label}**（约 **{cnt}** 家·{flag}）{tail}"


def mainline_source_note(decision: MainlineDecision) -> str:
    pin = os.environ.get("MAINLINE_KEYWORD", "").strip()
    if pin:
        return f"主线：**手动** `{pin}`（{decision.detail}）"
    return f"主线：**东财概念×连板网** — {decision.detail}"
