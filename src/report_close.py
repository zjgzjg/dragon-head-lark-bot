# -*- coding: utf-8 -*-
"""收盘复盘：固定模板（目录 + 表格 + 次日预案）。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.lianban_net import LianbanSummary, fetch_day_summary, fetch_latest_summary
from src.market_data import fetch_code_quote, fetch_watchlist_rows, fetch_zt_pool, summarize_zt
from src.trade_calendar import fmt_date, next_trade_date, prev_trade_date, weekday_cn


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


def _section_env(
    date: str,
    prev_d: str,
    sm_cur,
    sm_prev,
    lb_cur: Optional[LianbanSummary],
    lb_prev: Optional[LianbanSummary],
) -> List[str]:
    def val_lb(lb: Optional[LianbanSummary], attr: str, fallback: str = "—") -> str:
        if not lb:
            return fallback
        v = getattr(lb, attr, None)
        if v is None:
            return fallback
        if attr == "seal_rate":
            return f"{v:.1f}%"
        if attr == "max_board":
            return f"{int(v)}板"
        if attr == "temp":
            return f"{v:.0f}°"
        return str(v)

    prev_zt = lb_prev.zt if lb_prev else sm_prev.count
    cur_zt = lb_cur.zt if lb_cur else (sm_cur.count if sm_cur.count else "—")
    prev_dt = lb_prev.dt if lb_prev else "—"
    cur_dt = lb_cur.dt if lb_cur else "—"
    prev_seal = f"{lb_prev.seal_rate:.1f}%" if lb_prev else "—"
    cur_seal = f"{lb_cur.seal_rate:.1f}%" if lb_cur else "—"
    prev_h = lb_prev.max_board if lb_prev else sm_prev.max_height
    cur_h = lb_cur.max_board if lb_cur else (f"{sm_cur.max_height}板" if sm_cur.max_height else "—")
    prev_temp = lb_prev.temp if lb_prev and lb_prev.temp is not None else None
    cur_temp = lb_cur.temp if lb_cur and lb_cur.temp is not None else None

    lines = [
        "## 一、环境",
        "",
        "| 指标 | {} | {} 收盘 | 含义 |".format(
            fmt_date(prev_d), fmt_date(date)
        ),
        "| --- | --- | --- | --- |",
    ]
    rows = [
        ("涨停", prev_zt, cur_zt, "zt"),
        ("跌停", prev_dt, cur_dt, "dt"),
        ("封板率", prev_seal, cur_seal, "seal"),
        ("最高板", f"{prev_h}板" if isinstance(prev_h, int) else prev_h, f"{cur_h}板" if isinstance(cur_h, int) else cur_h, "height"),
    ]
    for label, a, b, key in rows:
        meaning = "—"
        try:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                meaning = _env_meaning(key, float(a), float(b))
        except (TypeError, ValueError):
            pass
        lines.append(f"| {label} | {a} | {b} | {meaning} |")

    emo_prev = f"{lb_prev.phase} {val_lb(lb_prev, 'temp')}" if lb_prev else "—"
    emo_cur = f"{lb_cur.phase} {val_lb(lb_cur, 'temp')}" if lb_cur else "—"
    temp_mean = "—"
    if prev_temp is not None and cur_temp is not None:
        temp_mean = _env_meaning("temp", prev_temp, cur_temp)
    lines += [
        f"| 情绪 | {emo_prev} | {emo_cur} | {temp_mean} |",
        "",
        f"**大前提对应动作：** {_premise_action(lb_cur)}",
    ]
    if lb_cur and lb_cur.one_liner:
        lines.append(f"\n> 连板网结论：{lb_cur.one_liner}")
    return lines


def _section_mainline(df: pd.DataFrame, lb: Optional[LianbanSummary]) -> List[str]:
    theme, cnt = _top_theme(df)
    lines = [
        "",
        "## 二、主线",
        "",
        "| 维度 | 数据 |",
        "| --- | --- |",
    ]
    if _has_zt_pool(df):
        lines.append(f"| 东财池涨停家数 | **{len(df)}** |")
        lines.append(f"| 池内行业首位 | **{theme}**（约 **{cnt}** 家） |")
    elif lb:
        lines.append(f"| 连板网涨停家数 | **{lb.zt}** |")
        lines.append(f"| 连板网连板家数 | **{lb.lianban}** |")
    if lb:
        lines.append(f"| 连板网主线标签 | **{lb.themes}** |")
        if lb.one_liner:
            lines.append(f"| 当日结论 | {lb.one_liner} |")
    if lb and lb.ai_snippet:
        lines.append("")
        lines.append(f"**连板网 AI 摘要：** {lb.ai_snippet}")
    lines.append("")
    lines.append(
        "**四步「认龙头」提示：** 以 **首封时间** + **硬条件表** 为准；"
        "名在池内但炸板/换手/封单不过关 → 只观察不接力。"
    )
    return lines


def _section_prev_watch(watch_codes: List[str], df: pd.DataFrame) -> List[str]:
    lines = ["", "## 三、与前一日观察名单对照", "", "| 代码 | 名称 | 今日表现 | 备注 |", "| --- | --- | --- | --- |"]
    if not watch_codes:
        lines.append("| — | — | 未配置 WATCHLIST | — |")
        return lines
    for code in watch_codes:
        code = code.strip()
        if not code:
            continue
        row = df[df["代码"].astype(str) == code] if _has_zt_pool(df) else pd.DataFrame()
        if len(row):
            r = row.iloc[0]
            perf = f"{int(r['连板数'])}板 收{float(r['最新价']):.2f} 炸{int(r['炸板次数'])}"
            note = "硬条件过关" if _hard_pass(r) else "；".join(_veto_reasons(r))
        else:
            wr = fetch_watchlist_rows([code], df)
            if wr and not wr[0].get("error"):
                w = wr[0]
                if w.get("in_zt"):
                    perf = f"{w.get('height')}板 收{w['close']:.2f}"
                else:
                    perf = f"收{w.get('close', '—')} ({w.get('pct', 0):+.2f}%)" if w.get("pct") is not None else "未涨停"
                note = "不在今日涨停池"
            else:
                perf = "—"
                note = "数据缺失"
        name = row.iloc[0]["名称"] if len(row) else code
        lines.append(f"| {code} | {name} | {perf} | {note} |")
    return lines


def _section_watch_plan(
    date: str,
    strict: pd.DataFrame,
    df: pd.DataFrame,
    watch_codes: List[str],
    thermometer: str,
) -> List[str]:
    nd = next_trade_date(date)
    nd_label = f"{fmt_date(nd)}（{weekday_cn(nd)}）"
    lines = [
        "",
        "## 四、今日观察名单 + 次日预案",
        "",
        "### 4.1 硬条件筛完（涨停池）",
        "",
        "| 条件 | 说明 |",
        "| --- | --- |",
        "| 连板 ≥2 | 与主线方向一致（可设 MAINLINE_KEYWORD） |",
        "| 封单占流通 ≥3% | 硬门槛 |",
        "| 炸板 <3 | 硬门槛 |",
        "| 换手 ≤20% | 硬门槛 |",
        "| 非 14:00 后首封 | 硬门槛 |",
        "",
        "**严格过关：**",
        "",
        "| 代码 | 名称 | 板数 | 首封 | 封单比 | 炸 | 换手 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    if strict.empty:
        lines.append("| — | 无 | — | — | — | — | — |")
    else:
        for _, r in strict.iterrows():
            lines.append(
                f"| {r['代码']} | {r['名称']} | {int(r['连板数'])}板 | {r['首次封板时间']} | "
                f"{r['封单比']:.2f}% | {int(r['炸板次数'])} | {r['换手率']:.1f}% |"
            )

    lines += ["", "**否决（勿进接力池）：**"]
    veto_lines: List[str] = []
    codes_check = set(watch_codes) | (
        set(strict["代码"].astype(str).tolist()) if len(strict) else set()
    )
    for code in codes_check:
        code = str(code).strip()
        if not _has_zt_pool(df):
            break
        row = df[df["代码"].astype(str) == code]
        if not len(row):
            continue
        r = row.iloc[0]
        if _hard_pass(r):
            continue
        reasons = _veto_reasons(r)
        if reasons:
            veto_lines.append(f"- **{r['名称']}** `{code}`：{'；'.join(reasons)}")
    if not _has_zt_pool(df):
        lines.append("- ⚠️ 东财涨停池不可用（如 GitHub Actions），否决线请本地/连板网人工核对。")
    else:
        lines.extend(veto_lines or ["- （池内连板票均须个别核对）"])

    next_items = _build_next_watchlist(strict, watch_codes, df, thermometer)
    lines += [
        "",
        f"### 4.2 **{nd_label}** 观察名单（{len(next_items)} 只）",
        "",
        "| # | 代码 | 名称 | 角色 | 今收 | 次日涨停价（约） |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for i, it in enumerate(next_items, 1):
        lines.append(
            f"| {i} | {it['code']} | {it['name']} | {it['role']} | "
            f"{it['close']:.2f} | {it['limit']:.2f} |"
        )

    lines += ["", f"### 4.3 **{nd_label}** 触发价 & 止损（今收为锚）", ""]
    for it in next_items:
        if it["code"] == thermometer:
            lines += [
                f"#### {it['name']} `{it['code']}`（体温计）",
                "",
                "| 体温 | 次日动作 |",
                "| --- | --- |",
                "| 一字 / 快速回封 | 主线权限↑；仍可不买买体温计 |",
                "| 低开 >2% 或破昨收且收不回 | 观察名单降级或关闭 |",
                "| 开板 15 分钟不回封 | 全线关闭 |",
                "",
            ]
            continue
        c, o = it["close"], it["close"] * 0.97
        lines += [
            f"#### {it['name']} `{it['code']}`",
            "",
            "| 项目 | 规则 |",
            "| --- | --- |",
            f"| 竞价 | 低开 >2% → 删；一字 → 不买，只确认板块 |",
            f"| 买入触发 | 9:30–9:40 不破开 + 放量 + 板块同步；**9:35–9:45** |",
            f"| 可接受区 | 平开～+3%；不追 >7% |",
            f"| 止损 | 昨收 **{c:.2f}** 或 当日开盘价 ×0.97 |",
            "",
        ]
    return lines


def _section_exec(next_date: str) -> List[str]:
    nd = fmt_date(next_date)
    return [
        "",
        "## 五、执行顺序（9:25 → 10:00）",
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


def _one_liner(next_items: List[dict], next_date: str) -> str:
    codes = [x for x in next_items if "体温计" not in x["role"]]
    main = "、".join(f"「{x['name']}」" for x in codes[:2]) or "硬板龙头"
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

    df_line = _mainline_filter(df) if pool_ok else df
    if not lb_cur:
        lb_cur = fetch_day_summary(date)
    lb_prev = fetch_day_summary(prev_d)
    strict = _pick_strict(df_line if _has_zt_pool(df_line) else df)

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
        "**目录**",
        "1. 环境",
        "2. 主线",
        "3. 与前一日观察名单对照",
        "4. 观察名单 + 次日预案",
        "5. 执行顺序",
        "6. 一句话",
        "",
    ]

    df_for_watch = df if pool_ok else df
    df_for_watch.attrs["date"] = date
    next_items = _build_next_watchlist(strict, watch_codes, df_for_watch, thermometer)

    parts = header
    parts += _section_env(date, prev_d, sm_cur, sm_prev, lb_cur, lb_prev)
    parts += _section_mainline(df, lb_cur)
    parts += _section_prev_watch(watch_codes, df_for_watch)
    parts += _section_watch_plan(date, strict, df_for_watch, watch_codes, thermometer)
    parts += _section_exec(nd)
    parts += ["", "## 六、一句话", "", _one_liner(next_items, nd), "", "> 方法论复盘，不构成投资建议。"]
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
                        "你是 A 股短线复盘助手。只补充「二、主线」下 2–4 句叙述"
                        "（换龙头/杀高度/资金分流），保留全部表格与数字不变，不要删目录。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"{method}\n\n在下列报告中仅扩写「二、主线」段落：\n\n{text}",
                },
            ],
            temperature=0.3,
        )
        return resp.choices[0].message.content or text
    except Exception:
        return text
