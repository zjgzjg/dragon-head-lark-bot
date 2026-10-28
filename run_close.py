#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.lark_webhook import send_feishu_post
from src.report_image import render_markdown_long_image
from src.trade_calendar import default_close_trade_date
from src.report_close import build_close_report, maybe_llm_polish
from src.watchlist import parse_manual_watchlist


def main() -> int:
    date = os.environ.get("TRADE_DATE") or default_close_trade_date()
    watch = parse_manual_watchlist()
    thermometer = os.environ.get("THERMOMETER", "").strip()

    from src.trade_calendar import weekday_cn

    title = f"{date[:4]}-{date[4:6]}-{date[6:8]}（{weekday_cn(date)}）收盘复盘"
    try:
        body = build_close_report(date, watch, thermometer)
        body = maybe_llm_polish(body)
    except Exception as exc:
        body = (
            f"## {title}\n\n> 生成异常 `{type(exc).__name__}`，请查看 Actions 日志。\n\n"
            f"WATCHLIST: `{', '.join(watch)}`"
        )
    try:
        img = render_markdown_long_image(body, title=title)
        send_feishu_post(body, title=title, image_path=img)
    except Exception as exc:
        print(f"Feishu send failed: {exc}", file=sys.stderr)
        return 1
    from src.watchlist_snapshot import load_snapshot_for_session, snapshot_path
    from src.trade_calendar import next_trade_date

    nd = next_trade_date(date)
    snap = load_snapshot_for_session(nd)
    if snap:
        print(f"OK close report sent; snapshot session={nd} path={snapshot_path()}")
    else:
        print(f"WARN close sent but snapshot missing for session {nd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
