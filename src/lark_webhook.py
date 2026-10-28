# -*- coding: utf-8 -*-
"""飞书自定义机器人 Webhook（与 daily_stock_analysis 同思路）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

import requests


def _sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def send_feishu_text(text: str, *, title: Optional[str] = None) -> Dict[str, Any]:
    url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("FEISHU_WEBHOOK_URL 未配置")

    secret = os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip()
    payload: Dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title or "龙头战法推送"},
                "template": "blue",
            },
            "elements": [
                {"tag": "markdown", "content": text[:8000]},  # 飞书卡片长度限制
            ],
        },
    }
    if secret:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(secret, ts)

    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, None):
        raise RuntimeError(f"飞书返回错误: {data}")
    return data


def send_feishu_post(markdown: str, *, title: str) -> Dict[str, Any]:
    """超长内容时分段发送（简易）。"""
    chunk = 7500
    parts = [markdown[i : i + chunk] for i in range(0, len(markdown), chunk)] or [""]
    last = {}
    for i, part in enumerate(parts):
        t = title if len(parts) == 1 else f"{title} ({i + 1}/{len(parts)})"
        last = send_feishu_text(part, title=t)
    return last
