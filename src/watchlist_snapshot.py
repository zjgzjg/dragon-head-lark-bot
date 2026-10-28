# -*- coding: utf-8 -*-
"""收盘定版名单 → 次日竞价读取（GitHub Actions cache 持久化）。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT = Path(__file__).resolve().parents[1] / "watchlist_snapshot.json"


def snapshot_path() -> Path:
    raw = os.environ.get("WATCHLIST_SNAPSHOT_PATH", "").strip()
    return Path(raw) if raw else _DEFAULT


def save_next_day_snapshot(
    *,
    list_date: str,
    session_date: str,
    thermometer: str,
    watch_codes: List[str],
    names: Dict[str, str],
) -> None:
    payload = {
        "list_date": list_date,
        "session_date": session_date,
        "thermometer": thermometer.strip(),
        "watch": [c.strip() for c in watch_codes if c.strip()],
        "names": {str(k).strip(): str(v) for k, v in names.items() if k},
    }
    path = snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_snapshot_for_session(session_yyyymmdd: str) -> Optional[Dict[str, Any]]:
    path = snapshot_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if str(data.get("session_date", "")).strip() != session_yyyymmdd.strip():
        return None
    return data
