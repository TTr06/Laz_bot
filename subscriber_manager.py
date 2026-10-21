"""
Subscriber Manager for Telegram Bot
Quản lý danh sách người dùng nhận thông báo biến động giá tự động.
"""

import json
import os
from typing import List, Set

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBSCRIBERS_FILE = os.path.join(BASE_DIR, "subscribers.json")


def _load_data() -> dict:
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"subscribers": [], "auto_track_enabled": True}


def _save_data(data: dict) -> None:
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_subscribers() -> List[int]:
    data = _load_data()
    return data.get("subscribers", [])


def add_subscriber(chat_id: int) -> bool:
    data = _load_data()
    subs = set(data.get("subscribers", []))
    if chat_id not in subs:
        subs.add(chat_id)
        data["subscribers"] = list(subs)
        _save_data(data)
        return True
    return False


def remove_subscriber(chat_id: int) -> bool:
    data = _load_data()
    subs = set(data.get("subscribers", []))
    if chat_id in subs:
        subs.remove(chat_id)
        data["subscribers"] = list(subs)
        _save_data(data)
        return True
    return False


def is_auto_track_enabled() -> bool:
    data = _load_data()
    return data.get("auto_track_enabled", True)


def set_auto_track_enabled(enabled: bool) -> None:
    data = _load_data()
    data["auto_track_enabled"] = enabled
    _save_data(data)
