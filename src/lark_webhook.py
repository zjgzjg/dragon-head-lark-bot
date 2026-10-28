# -*- coding: utf-8 -*-
"""飞书自定义机器人 Webhook（与 daily_stock_analysis 同思路）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

_TOKEN_CACHE: Dict[str, Any] = {"token": "", "expire": 0.0}


def _sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def _webhook_payload(extra: Dict[str, Any]) -> Dict[str, Any]:
    url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("FEISHU_WEBHOOK_URL 未配置")
    payload = dict(extra)
    secret = os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip()
    if secret:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(secret, ts)
    return payload


def _post_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, None):
        raise RuntimeError(f"飞书返回错误: {data}")
    return data


def _tenant_access_token() -> Optional[str]:
    direct = os.environ.get("FEISHU_TENANT_ACCESS_TOKEN", "").strip()
    if direct:
        return direct
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        return None
    now = time.time()
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expire"] > now + 60:
        return str(_TOKEN_CACHE["token"])
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书 token 失败: {data}")
    token = data["tenant_access_token"]
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expire"] = now + int(data.get("expire", 7200))
    return token


def upload_feishu_image(image_path: Path) -> str:
    token = _tenant_access_token()
    if not token:
        raise RuntimeError("未配置 FEISHU_APP_ID/FEISHU_APP_SECRET，无法上传长图")
    with image_path.open("rb") as f:
        r = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/images",
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": (image_path.name, f, "image/png")},
            timeout=60,
        )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书图片上传失败: {data}")
    return str(data["data"]["image_key"])


def send_feishu_image_card(*, title: str, image_key: str, hint: str = "") -> Dict[str, Any]:
    elements = [
        {
            "tag": "img",
            "img_key": image_key,
            "mode": "fit_horizontal",
            "alt": {"tag": "plain_text", "content": title[:50]},
        }
    ]
    if hint:
        elements.insert(0, {"tag": "markdown", "content": hint[:500]})
    payload = _webhook_payload(
        {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title[:100]},
                    "template": "blue",
                },
                "elements": elements,
            },
        }
    )
    return _post_webhook(payload)


def send_feishu_text(text: str, *, title: Optional[str] = None) -> Dict[str, Any]:
    payload = _webhook_payload(
        {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title or "龙头战法推送"},
                    "template": "blue",
                },
                "elements": [
                    {"tag": "markdown", "content": text[:8000]},
                ],
            },
        }
    )
    return _post_webhook(payload)


def send_feishu_post(
    markdown: str,
    *,
    title: str,
    image_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """先发长图（若有），再分段发 Markdown 文本。"""
    last: Dict[str, Any] = {}
    if image_path and Path(image_path).is_file():
        try:
            img_key = upload_feishu_image(Path(image_path))
            last = send_feishu_image_card(
                title=f"📊 {title} · 长图",
                image_key=img_key,
                hint="> 完整 **表格版** 复盘见下图；下文为同内容文本便于复制检索。",
            )
        except Exception as exc:
            print(f"Feishu image push skipped: {exc}")

    chunk = 7500
    parts = [markdown[i : i + chunk] for i in range(0, len(markdown), chunk)] or [""]
    for i, part in enumerate(parts):
        t = title if len(parts) == 1 else f"{title} ({i + 1}/{len(parts)})"
        last = send_feishu_text(part, title=t)
    return last
