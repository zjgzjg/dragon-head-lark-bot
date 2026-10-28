# -*- coding: utf-8 -*-
"""收盘复盘：固定模板（目录 + 表格 + 次日预案）。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.lianban_net import LianbanSummary, fetch_day_summary, fetch_latest_summary
from src.market_data import fetch_code_quote, fetch_watchlist_rows, fetch_zt_pool, summarize_zt
from src.trade_calendar import fmt_date, next_trade_date, prev_trade_date, weekday_cn
from src.watchlist import (
    mainline_pool,
    resolve_thermometer,
    resolve_watch_codes,
    thermometer_source_note,
    watchlist_source_note,
)
from src.watchlist_snapshot import save_next_day_snapshot


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


def _veto_reasons(row: pd.Series) -> List[str]:
    rs: List[str] = []
    if int(row["连板数"]) < 2:
        rs.append("连板<2")
    if float(row["封单比"]) < 3:
        rs.append(f"封单{row['封单比']:.1f}%<3%")
    if int(row["炸板次数"]) >= 3:
        rs.append(f"{int(row['炸板次数'])}炸")
    if float(row["换手率"]) > 20:
        rs.append(f"换手{row['换手率']:.1f}%>20%")
    if int(row["首次封板时间"]) > 140000:
        rs.append("14:00后首封")
    return rs


def _limit_up_price(code: str, close: float) -> float:
    ratio = 1.2 if code.startswith(("300", "301", "688")) else 1.1
    return round(close * ratio, 2)


def _mainline_filter(df: pd.DataFrame) -> pd.DataFrame:
    kw = os.environ.get("MAINLINE_KEYWORD", "").strip()
    if not kw or df.empty:
        return df
    col = "所属行业" if "所属行业" in df.columns else None
    if col:
        return df[df[col].astype(str).str.contains(kw, na=False)]
    return df


def _top_theme(df: pd.DataFrame) -> Tuple[str, int]:
    if df.empty:
        return "—", 0
    col = "所属行业" if "所属行业" in df.columns else None
    if not col:
        return "—", len(df)
    vc = df[col].astype(str).value_counts()
    if vc.empty:
        return "—", 0
    return str(vc.index[0]), int(vc.iloc[0])


def _premise_action(lb: Optional[LianbanSummary]) -> str:
    if not lb:
        return "数据不足：半仓以下，只做硬筹码或空仓。"
    phase = lb.phase or ""
    if "冰点" in phase:
        return "**冰点**：空仓或只处理存量；非接力主场。"
    if "退潮" in phase:
        return "**退潮/半仓以下**：只做龙一、早封、硬筹码；否则空仓也合理。"
    if "修复" in phase:
        return "**修复**：可观察龙一，仍须板块同步与硬条件。"
    return f"**{phase}**：控制仓位，硬条件不过关不做。"


def _env_meaning(key: str, prev_v: float, cur_v: float) -> str:
    if key == "zt":
        if cur_v < prev_v * 0.85:
            return "明显降温"
        if cur_v > prev_v * 1.15:
            return "情绪回暖"
        return "震荡"
    if key == "dt":
        if cur_v > prev_v + 5:
            return "亏钱效应上来"
        if cur_v < prev_v - 5:
            return "跌停减少"
        return "分化"
    if key == "seal":
        if cur_v < prev_v - 8:
            return "溢价变差"
        if cur_v > prev_v + 8:
            return "封板改善"
        return "一般"
    if key == "height":
        if cur_v < prev_v:
            return "高度被切断"
        if cur_v > prev_v:
            return "高度抬升"
        return "持平"
    if key == "temp":
        if cur_v < prev_v - 10:
            return "情绪下台阶"
        if cur_v > prev_v + 10:
            return "情绪修复"
        return "小幅波动"
    return "—"


def _parse_roles() -> Dict[str, str]:
    raw = os.environ.get("WATCH_ROLES", "").strip()
    out: Dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if ":" in part:
            code, role = part.split(":", 1)
            out[code.strip()] = role.strip()
    return out


def _pick_strict(df: pd.DataFrame, max_n: int = 5) -> pd.DataFrame:
    if not _has_zt_pool(df):
        return pd.DataFrame()
    sub = df[df["连板数"] >= 2].copy()
    sub = sub.sort_values(["连板数", "首次封板时间"], ascending=[False, True])
    strict = sub[sub.apply(_hard_pass, axis=1)]
    return strict.head(max_n)


def _build_next_watchlist(
    strict: pd.DataFrame,
    watch_codes: List[str],
    df: pd.DataFrame,
    thermometer: str,
    max_n: int = 5,
) -> List[dict]:
    roles = _parse_roles()
    seen = set()
    items: List[dict] = []

    for _, r in strict.iterrows():
        code = str(r["代码"])
        if code in seen or code == thermometer:
            continue
        seen.add(code)
        close = float(r["最新价"])
        items.append(
            {
                "code": code,
                "name": r["名称"],
                "role": roles.get(code, "硬条件过关"),
                "close": close,
                "limit": _limit_up_price(code, close),
                "height": int(r["连板数"]),
            }
        )
        if len(items) >= max_n - 1:
            break

    trade_d = str(df.attrs.get("date") or "")

    for code in watch_codes:
        code = code.strip()
        if not code or code in seen or code == thermometer:
            continue
        added = False
        if _has_zt_pool(df):
            row = df[df["代码"].astype(str) == code]
            if len(row):
                r = row.iloc[0]
                seen.add(code)
                close = float(r["最新价"])
                items.append(
                    {
                        "code": code,
                        "name": r["名称"],
                        "role": roles.get(code, "观察池补入"),
                        "close": close,
                        "limit": _limit_up_price(code, close),
                        "height": int(r["连板数"]),
                    }
                )
                added = True
        if not added and trade_d:
            q = fetch_code_quote(code, trade_d)
            if not q.get("error"):
                seen.add(code)
                items.append(
                    {
                        "code": code,
                        "name": q.get("name", code),
                        "role": roles.get(code, "观察池"),
                        "close": float(q["close"]),
                        "limit": _limit_up_price(code, float(q["close"])),
                        "height": 0,
                    }
                )
        if len(items) >= max_n - 1:
            break

    if thermometer:
        tr = df[df["代码"].astype(str) == thermometer] if _has_zt_pool(df) else pd.DataFrame()
        close = float(tr.iloc[0]["最新价"]) if len(tr) else 0.0
        name = tr.iloc[0]["名称"] if len(tr) else thermometer
        height = int(tr.iloc[0]["连板数"]) if len(tr) else 0
        if not close and trade_d:
            q = fetch_code_quote(thermometer, trade_d)
            if not q.get("error"):
                close = float(q["close"])
                name = q.get("name", thermometer)
        if not close:
            wr = fetch_watchlist_rows([thermometer], df)
            if wr and wr[0].get("close"):
                close = float(wr[0]["close"])
                name = wr[0].get("name", thermometer)
                height = int(wr[0].get("height") or 0)
        items.append(
            {
                "code": thermometer,
                "name": name,
                "role": roles.get(thermometer, "仅体温计，默认不买"),
                "close": close,
                "limit": _limit_up_price(thermometer, close) if close else 0,
                "height": height,
            }
        )
    return items[:max_n]


def _md_short(yyyymmdd: str) -> str:
    return f"{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def _first_time_fmt(t: int) -> str:
    t = int(t)
    return f"{t // 10000:02d}:{(t // 100) % 100:02d}"


def _pool_row(df: pd.DataFrame, code: str) -> Optional[pd.Series]:
    if not _has_zt_pool(df):
        return None
    r = df[df["代码"].astype(str) == code.strip()]
    return r.iloc[0] if len(r) else None


def _mainline_narrative(df: pd.DataFrame, lb: Optional[LianbanSummary]) -> str:
    kw = os.environ.get("MAINLINE_KEYWORD", "机器人").strip() or "机器人"
    cnt = 0
    if _has_zt_pool(df):
        cnt = int(len(mainline_pool(df)))
        theme = kw
    elif lb and lb.themes:
        theme = lb.themes.split("、")[0]
        cnt = lb.zt // 3
        if lb.ai_snippet:
            m = re.search(r"机器人[^\d]{0,12}(\d+)只", lb.ai_snippet)
            if m:
                cnt = int(m.group(1))
                theme = "机器人"
    else:
        theme, cnt = _top_theme(df)
    tail = "，但 **缩圈抱团**" if lb and "冰点" in (lb.phase or "") else ""
    return f"**{theme}**（约 **{cnt}** 家）{tail}"


def _height_narrative(df: pd.DataFrame, lb: Optional[LianbanSummary]) -> str:
    if not _has_zt_pool(df):
        if lb:
            return f"最高 **{lb.max_board}板**（连板网）"
        return "—"
    max_h = int(df["连板数"].max())
    parts: List[str] = []
    sub = max_h - 1
    if sub >= 2:
        sub_df = df[df["连板数"] == sub]
        if len(sub_df):
            names = sub_df["名称"].astype(str).tolist()[:5]
            parts.append(f"**{sub}板** {len(sub_df)} 只：{'、'.join(names)}")
    top = df[df["连板数"] == max_h]
    for _, row in top.iterrows():
        ind = str(row.get("所属行业", ""))
        tag = "消费 " if any(k in ind for k in ("零售", "消费", "食品")) else ""
        parts.append(f"{tag}**{row['名称']}** **{max_h}板**")
    return "；".join(parts) if parts else f"最高 **{max_h}板**"


def _position_narrative(lb: Optional[LianbanSummary], therm_name: str) -> str:
    if not lb:
        return "≤半仓；只做硬筹码"
    if "冰点" in lb.phase:
        return f"**≤半仓 / 偏空**；**{therm_name}** 只当体温计"
    if "退潮" in lb.phase:
        return f"**≤半仓**；**{therm_name}** 只当体温计"
    return f"控制仓位；**{therm_name}** 只当体温计"


def _hard_note(code: str, df: pd.DataFrame, best_seal: float) -> str:
    r = _pool_row(df, code)
    if r is None:
        return "不在涨停池"
    reasons = _veto_reasons(r)
    if not reasons:
        return "严格过关"
    note = "；".join(reasons)
    seal = float(r["封单比"])
    if best_seal > 0 and abs(seal - best_seal) < 0.05:
        note = f"**相对最硬**（仍 {note}）" if seal < 3 else "**相对最硬**"
    return note


def _auto_role(code: str, df: pd.DataFrame, roles: Dict[str, str], thermometer: str) -> str:
    if code == thermometer:
        return roles.get(code, "只当体温计，默认不买")
    if roles.get(code):
        return roles[code]
    r = _pool_row(df, code)
    if r is not None:
        ft = _first_time_fmt(int(r["首次封板时间"]))
        z = int(r["炸板次数"])
        t = float(r["换手率"])
        h = int(r["连板数"])
        qual = "质量龙" if z == 0 and t <= 5 else ""
        return f"{h}板 · 首封{ft} · {z}炸 · 换{t:.1f}%{(' · ' + qual) if qual else ''}"
    return "观察池"


def _close_cell(code: str, df: pd.DataFrame, trade_date: str) -> Tuple[str, float]:
    r = _pool_row(df, code)
    if r is not None:
        return "涨停", float(r["最新价"])
    q = fetch_code_quote(code, trade_date)
    if q.get("error"):
        return "—", 0.0
    close = float(q["close"])
    if q.get("in_zt"):
        return "涨停", close
    pct = q.get("pct")
    if pct is not None:
        return f"{close:.2f} ({pct:+.2f}%)", close
    return f"{close:.2f}", close


def build_watch_table_rows(
    watch_codes: List[str],
    thermometer: str,
    df: pd.DataFrame,
    trade_date: str,
    max_n: int = 5,
) -> List[dict]:
    roles = _parse_roles()
    codes: List[str] = []
    for c in watch_codes:
        c = c.strip()
        if c and c != thermometer and c not in codes:
            codes.append(c)
    codes = codes[: max_n - 1]
    if thermometer and thermometer not in codes:
        codes.append(thermometer)

    seals: List[float] = []
    for c in codes:
        r = _pool_row(df, c)
        if r is not None:
            seals.append(float(r["封单比"]))
    best_seal = max(seals) if seals else 0.0

    rows: List[dict] = []
    for i, code in enumerate(codes, 1):
        close_txt, close = _close_cell(code, df, trade_date)
        r = _pool_row(df, code)
        name = str(r["名称"]) if r is not None else fetch_code_quote(code, trade_date).get("name", code)
        rows.append(
            {
                "idx": i,
                "code": code,
                "name": name,
                "role": _auto_role(code, df, roles, thermometer),
                "close_txt": close_txt,
                "close": close,
                "limit": _limit_up_price(code, close) if close else 0,
                "hard_note": _hard_note(code, df, best_seal),
            }
        )
    return rows


def _section_env_compact(
    date: str,
    nd: str,
    lb_cur: Optional[LianbanSummary],
    df: pd.DataFrame,
    thermometer: str,
    therm_name: str,
) -> List[str]:
    zt = lb_cur.zt if lb_cur else (len(df) if _has_zt_pool(df) else "—")
    dt = lb_cur.dt if lb_cur else "—"
    seal = f"{lb_cur.seal_rate:.0f}%" if lb_cur else "—"
    temp = f"{lb_cur.temp:.0f}°" if lb_cur and lb_cur.temp is not None else "—"
    phase = lb_cur.phase.replace("期", "") if lb_cur else "—"
    emo = f"**{phase}** ~**{temp}**（{zt} 涨停、{dt} 跌停、封板率 ~{seal}）"
    return [
        "",
        f"## 一、{_md_short(date)} 收盘环境 → {_md_short(nd)} 名单前提",
        "",
        "| 环境 | 数据 |",
        "| --- | --- |",
        f"| **情绪** | {emo} |",
        f"| **主线** | {_mainline_narrative(df, lb_cur)} |",
        f"| **高度** | {_height_narrative(df, lb_cur)} |",
        f"| **仓位** | {_position_narrative(lb_cur, therm_name)} |",
    ]


def _section_watch_table(date: str, nd: str, rows: List[dict]) -> List[str]:
    lines = [
        "",
        f"## 二、{_md_short(nd)} 观察名单（{_md_short(date)} 收盘后应写进笔记的 **{len(rows)}** 只）",
        "",
        f"| # | 代码 | 名称 | 角色 | {_md_short(date)} 收 | 硬条件备注 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['idx']} | {r['code']} | {r['name']} | {r['role']} | "
            f"{r['close_txt']} | {r['hard_note']} |"
        )
    return lines


def _section_triggers(nd: str, rows: List[dict], thermometer: str) -> List[str]:
    nd_label = f"{fmt_date(nd)}（{weekday_cn(nd)}）"
    lines = [
        "",
        f"## 三、{nd_label} 触发价 & 止损（昨收为锚）",
        "",
        "| 代码 | 名称 | 昨收 | 涨停价 | 竞价/买点/止损 |",
        "| --- | --- | --- | --- | --- |",
    ]
    rule = "低开>2%删；9:35–9:45承接；止损昨收或开×0.97"
    for r in rows:
        if r["code"] == thermometer:
            lines.append(
                f"| {r['code']} | {r['name']}（体温） | {r['close']:.2f} | {r['limit']:.2f} | "
                "一字/回封=权限↑；低开>2%或15分不回封=关闭 |"
            )
        else:
            lines.append(
                f"| {r['code']} | {r['name']} | {r['close']:.2f} | {r['limit']:.2f} | {rule} |"
            )
    return lines


def _section_exec(next_date: str) -> List[str]:
    nd = fmt_date(next_date)
    return [
        "",
        "## 四、执行顺序（9:25 → 10:00）",
        "",
        "```",
        f"9:25  先看体温计 → 定「可玩 / 只观察 / 关闭」",
        f"      再看观察名单竞价 → 低开>2% 删掉",
        f"9:30  承接三件套（不破开、放量、板块同步）",
        f"9:35–9:45  唯一可下单窗口",
        f"10:00  低开票不翻红 → 走/不做",
        "```",
        "",
        f"**板块同步（{nd}）：** 名单内至少 **2 只** 在开盘价之上且不强杀；"
        "体温计单独强、梯队弱 → 不做。",
    ]


def _one_liner(watch_rows: List[dict], next_date: str, thermometer: str) -> str:
    picks = [x for x in watch_rows if x["code"] != thermometer]
    main = "、".join(f"「{x['name']}」" for x in picks[:2]) or "硬板龙头"
    return (
        f"**{fmt_date(next_date)}** 只盯：{main} 为主力观察，体温计定开关；"
        "退潮下半仓，竞价只否决、**9:35–9:45** 才执行。"
    )


def build_close_report(date: str, watch_codes: List[str], thermometer: str) -> str:
    orig_date = date
    lb_cur = fetch_day_summary(date)
    if not lb_cur:
        lb_latest = fetch_latest_summary()
        if lb_latest:
            date = lb_latest.date_iso.replace("-", "")
            lb_cur = lb_latest

    prev_d = prev_trade_date(date)
    nd = next_trade_date(date)

    df = pd.DataFrame()
    df.attrs["date"] = date
    sm_cur = summarize_zt(df, date)
    sm_prev = summarize_zt(df, prev_d)
    pool_ok = False
    try:
        df = fetch_zt_pool(date)
        df.attrs["date"] = date
        sm_cur = summarize_zt(df, date)
        pool_ok = _has_zt_pool(df)
    except Exception:
        df = pd.DataFrame()
        df.attrs["date"] = date
    df_prev = pd.DataFrame()
    try:
        df_prev = fetch_zt_pool(prev_d)
        df_prev.attrs["date"] = prev_d
        sm_prev = summarize_zt(df_prev, prev_d)
    except Exception:
        sm_prev = summarize_zt(df_prev, prev_d)

    if not lb_cur:
        lb_cur = fetch_day_summary(date)

    header = [
        f"# {fmt_date(date)}（{weekday_cn(date)}）收盘复盘",
        "",
        f"**定版口径：** 东财涨停池 + [连板网](https://lianban.net/) {fmt_date(date)} 公开复盘；"
        "个股价以收盘池/日线为准。",
    ]
    if orig_date != date:
        header.append(
            f"> 📅 自然日 `{fmt_date(orig_date)}` 尚无连板网定版，已改用最近归档 **{fmt_date(date)}**。"
        )
    if not pool_ok:
        header.append(
            "> ⚠️ **东财涨停池未拉取**（云端限流时常见）：环境/主线以 **连板网** 为准；"
            "观察名单价用 **新浪日线/实时**；硬条件表可能为空。"
        )
    header += [
        "",
        "**目录**：① 环境→名单前提 ② 观察名单 ③ 触发止损 ④ 执行顺序 ⑤ 一句话",
        "",
    ]

    df_for_watch = df if pool_ok else df
    df_for_watch.attrs["date"] = date
    thermometer = (thermometer or "").strip() or resolve_thermometer(df_for_watch)
    resolved = resolve_watch_codes(df_for_watch, thermometer, watch_codes)
    watch_rows = build_watch_table_rows(resolved, thermometer, df_for_watch, date)
    therm_name = next((r["name"] for r in watch_rows if r["code"] == thermometer), thermometer)

    save_next_day_snapshot(
        list_date=date,
        session_date=nd,
        thermometer=thermometer,
        watch_codes=resolved,
        names={str(r["code"]): str(r["name"]) for r in watch_rows},
    )

    parts = header
    parts += _section_env_compact(date, nd, lb_cur, df, thermometer, therm_name)
    if lb_cur and lb_cur.one_liner:
        parts.append(f"\n> 连板网：{lb_cur.one_liner}")
    parts.append(f"\n> {watchlist_source_note()}")
    parts.append(f"> {thermometer_source_note(thermometer)}")
    parts += _section_watch_table(date, nd, watch_rows)
    parts += _section_triggers(nd, watch_rows, thermometer)
    parts += _section_exec(nd)
    parts += ["", "## 五、一句话", "", _one_liner(watch_rows, nd, thermometer), "", "> 方法论复盘，不构成投资建议。"]
    return "\n".join(parts)


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
                    "content": (
                        "你是 A 股短线复盘助手。只补充「一、环境」表格中「高度/主线」行后的半句叙述，"
                        "保留全部表格与数字不变。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"{method}\n\n在下列报告中仅扩写环境表中高度/主线相关表述：\n\n{text}",
                },
            ],
            temperature=0.3,
        )
        return resp.choices[0].message.content or text
    except Exception:
        return text
