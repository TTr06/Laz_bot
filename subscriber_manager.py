"""
Subscriber Manager for Telegram Bot (SQLite Backed)
Quản lý danh sách người dùng nhận thông báo biến động giá tự động qua SQLite.
"""

from typing import List
import database


def get_subscribers() -> List[int]:
    return database.get_subscribers_db()


def add_subscriber(chat_id: int) -> bool:
    return database.add_subscriber_db(chat_id)


def remove_subscriber(chat_id: int) -> bool:
    return database.remove_subscriber_db(chat_id)


def is_auto_track_enabled() -> bool:
    return database.is_auto_track_enabled_db()


def set_auto_track_enabled(enabled: bool) -> None:
    database.set_auto_track_enabled_db(enabled)
