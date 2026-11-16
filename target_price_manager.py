"""
Target Price Manager Module (SQLite Backed)
Quản lý mức Giá đáy (Target Price) cho từng sản phẩm trong giỏ hàng.
Đảm bảo Số thứ tự (STT 1, 2, 3...) luôn chuẩn xác 100% theo danh sách giỏ hàng.
"""

from typing import Optional, Tuple, Dict, Any, List
import database


def parse_user_price(text: str) -> Optional[float]:
    return database.parse_user_price(text)


def parse_quick_setprice_input(text: str):
    return database.parse_quick_setprice_input(text)


def parse_quick_del_input(text: str):
    return database.parse_quick_del_input(text)


def load_target_prices() -> Dict[str, Dict[str, Any]]:
    items = database.get_all_target_prices_db()
    result = {}
    for it in items:
        result[it["pid"]] = {
            "name": it["name"],
            "sku": it["sku"],
            "target_price": it["target_price"],
            "url": it["url"],
            "stt": it.get("stt"),
            "current_price": it.get("current_price"),
            "set_at": it.get("created_at")
        }
    return result


def save_target_prices(data: Dict[str, Dict[str, Any]]) -> None:
    # Không cần lưu file JSON nữa, dữ liệu đã lưu tức thì trong SQLite
    pass


def set_target_price(pid: str, name: str, sku: str, target_price: float, url: str = "") -> Dict[str, Any]:
    return database.set_target_price_db(pid, name, sku, target_price, url)


def remove_target_price(pid: str) -> bool:
    return database.remove_target_price_db(pid)


def clear_all_target_prices() -> int:
    return database.clear_all_target_prices_db()


def get_target_price(pid: str) -> Optional[float]:
    return database.get_target_price_db(pid)


def get_all_target_prices() -> Dict[str, Dict[str, Any]]:
    return load_target_prices()


def should_notify_price_change(pid: str, old_price: Optional[float], new_price: Optional[float]) -> Tuple[bool, Optional[float]]:
    return database.should_notify_price_change_db(pid, old_price, new_price)


def find_product_by_query(query: str) -> Optional[Tuple[str, Dict[str, Any], int]]:
    """
    Tìm sản phẩm theo:
    1. Số thứ tự STT (1, 2, 3...) chuẩn xác 100% theo giỏ hàng.
    2. Từ khóa tên hoặc SKU.
    Trả về (pid, product_dict, stt)
    """
    res = database.find_product_by_stt_or_query(query)
    if not res:
        return None

    pid = res["pid"]
    stt = res["stt"]
    p_data = {
        "name": res["name"],
        "sku": res["sku"],
        "current_price": res["price"],
        "base_price": res["base_price"],
        "valid": bool(res["valid"]),
        "url": res["url"],
        "stt": stt
    }
    return pid, p_data, stt
