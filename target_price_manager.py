"""
Target Price Manager Module
Quản lý mức giá mục tiêu (Target Price Alert) cho từng sản phẩm trong giỏ hàng:
- Cho phép người dùng đặt mức giá mong muốn qua Telegram (/setprice <stt/tên> <giá>)
- Chỉ gửi thông báo biến động khi giá sản phẩm GIẢM XUỐNG THẤP HƠN HOẶC BẰNG (<=) mức giá đã đặt.
- Các sản phẩm không đặt mức giá mục tiêu thì vẫn thông báo biến động như bình thường.
"""

import json
import os
import re
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_PRICES_FILE = os.path.join(BASE_DIR, "target_prices.json")
PRICE_HISTORY_FILE = os.path.join(BASE_DIR, "price_history.json")


def parse_user_price(text: str) -> Optional[float]:
    """
    Chuyển đổi chuỗi nhập giá của người dùng thành số thực:
    - 100k, 100K -> 100000
    - 1.5tr, 1,5m, 2tr -> 1500000, 2000000
    - 100.000, 100,000, 100000 -> 100000
    - 85 -> 85000 (nếu số < 1000 thì quy ước nghìn)
    """
    if not text:
        return None
    cleaned = text.strip().lower()
    cleaned = cleaned.replace("₫", "").replace("đ", "").replace("vnd", "").strip()

    # 1. Định dạng triệu: 1.5tr, 1.5m, 2tr
    m_tr = re.match(r'^([\d.,]+)\s*(?:tr|trieu|triệu|m)$', cleaned)
    if m_tr:
        num_str = m_tr.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000_000
        except ValueError:
            pass

    # 2. Định dạng nghìn: 100k, 150.5k
    m_k = re.match(r'^([\d.,]+)\s*k$', cleaned)
    if m_k:
        num_str = m_k.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000
        except ValueError:
            pass

    # 3. Định dạng số thông thường: 100.000, 100000, 100,000
    num_clean = re.sub(r'[^\d]', '', cleaned)
    if num_clean:
        try:
            val = float(num_clean)
            if 0 < val < 1000 and "k" not in cleaned:
                val = val * 1000
            return val
        except ValueError:
            pass

    return None


def load_target_prices() -> Dict[str, Dict[str, Any]]:
    """Đọc danh sách giá mục tiêu đã lưu"""
    if os.path.exists(TARGET_PRICES_FILE):
        try:
            with open(TARGET_PRICES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_target_prices(data: Dict[str, Dict[str, Any]]) -> None:
    """Lưu danh sách giá mục tiêu ra file JSON"""
    with open(TARGET_PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def set_target_price(pid: str, name: str, sku: str, target_price: float, url: str = "") -> Dict[str, Any]:
    """Đặt hoặc cập nhật mức giá mục tiêu cho sản phẩm"""
    targets = load_target_prices()
    targets[pid] = {
        "name": name,
        "sku": sku,
        "target_price": float(target_price),
        "url": url,
        "set_at": datetime.now().isoformat(),
        "last_notified_price": None
    }
    save_target_prices(targets)
    return targets[pid]


def remove_target_price(pid: str) -> bool:
    """Xóa mức giá mục tiêu của 1 sản phẩm"""
    targets = load_target_prices()
    if pid in targets:
        del targets[pid]
        save_target_prices(targets)
        return True
    return False


def clear_all_target_prices() -> int:
    """Xóa tất cả các mức giá mục tiêu đã đặt"""
    targets = load_target_prices()
    count = len(targets)
    if count > 0:
        save_target_prices({})
    return count


def get_target_price(pid: str) -> Optional[float]:
    """Lấy mức giá mục tiêu của 1 sản phẩm nếu có"""
    targets = load_target_prices()
    if pid in targets:
        return targets[pid].get("target_price")
    return None


def get_all_target_prices() -> Dict[str, Dict[str, Any]]:
    """Lấy toàn bộ danh sách giá mục tiêu"""
    return load_target_prices()


def should_notify_price_change(pid: str, old_price: Optional[float], new_price: Optional[float]) -> Tuple[bool, Optional[float]]:
    """
    Kiểm tra xem biến động giá của sản phẩm có đủ điều kiện gửi thông báo không:
    - Nếu sản phẩm KHÔNG ĐẶT giá mục tiêu: Luôn gửi thông báo (True, None).
    - Nếu sản phẩm CÓ ĐẶT giá mục tiêu:
      + Chỉ gửi khi GIÁ GIẢM XUỐNG <= mức giá quy định (True, target_price).
      + Nếu giá vẫn cao hơn mức giá quy định hoặc tăng giá: Không gửi (False, target_price).
    """
    target = get_target_price(pid)
    if target is None:
        # Không đặt giá mục tiêu -> Báo động như bình thường
        return True, None

    if new_price is None:
        return False, target

    # Sản phẩm có đặt giá mục tiêu: Chỉ báo khi giá giảm xuống <= giá mục tiêu
    is_price_drop = (old_price is not None and new_price < old_price)
    is_at_or_below_target = (new_price <= target)

    if is_price_drop and is_at_or_below_target:
        return True, target

    # Trường hợp giá cũ > target và giá mới rơi xuống <= target
    if old_price is not None and old_price > target and is_at_or_below_target:
        return True, target

    # Còn lại thì không gửi thông báo
    return False, target


def find_product_by_query(query: str) -> Optional[Tuple[str, Dict[str, Any], int]]:
    """
    Tìm sản phẩm trong danh sách giỏ hàng đã lưu (price_history.json) theo:
    1. Số thứ tự: 1, 2, 3...
    2. Từ khóa trong tên hoặc phân loại (SKU)
    Trả về (pid, product_dict, index)
    """
    if not os.path.exists(PRICE_HISTORY_FILE):
        return None

    try:
        with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            prods = data.get("products", {})
    except Exception:
        return None

    if not prods:
        return None

    prod_items = list(prods.items())

    # 1. Tìm theo số thứ tự (index bắt đầu từ 1)
    if query.isdigit():
        idx = int(query)
        if 1 <= idx <= len(prod_items):
            pid, p_data = prod_items[idx - 1]
            return pid, p_data, idx

    # 2. Tìm theo từ khóa trong tên hoặc SKU
    q_lower = query.strip().lower()
    for idx, (pid, p_data) in enumerate(prod_items, 1):
        name = p_data.get("name", "").lower()
        sku = p_data.get("sku", "").lower()
        if q_lower in name or q_lower in sku:
            return pid, p_data, idx

    return None
