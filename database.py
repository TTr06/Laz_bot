"""
Database Module for LazBot (SQLite Engine)
Tối ưu hiệu năng, lưu trữ đồng bộ giỏ hàng, lịch sử giá và mức giá đáy (Target Price).
Đảm bảo Số thứ tự (STT 1, 2, 3...) luôn chuẩn xác, không bị xáo trộn khi thêm/sửa giá đáy.
"""

import json
import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "lazbot.db")
LEGACY_TARGET_FILE = os.path.join(BASE_DIR, "target_prices.json")
LEGACY_HISTORY_FILE = os.path.join(BASE_DIR, "price_history.json")
LEGACY_SUBS_FILE = os.path.join(BASE_DIR, "subscribers.json")

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Lấy hoặc tạo kết nối SQLite cho luồng hiện tại với WAL mode"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Tối ưu hóa SQLite cho môi trường đa luồng / truy vấn nhanh
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA cache_size = -64000;")  # 64MB cache
        _local.conn = conn
    return conn


@contextmanager
def get_db():
    """Context manager hỗ trợ auto-commit và rollback khi có lỗi"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Lỗi database transaction: {e}", exc_info=True)
        raise


def init_db() -> None:
    """Khởi tạo bảng cơ sở dữ liệu và index hiệu năng cao"""
    with get_db() as conn:
        conn.executescript("""
            -- 1. Bảng giỏ hàng chuẩn hóa (STT 1, 2, 3... làm khóa định danh hiển thị)
            CREATE TABLE IF NOT EXISTS cart_items (
                stt INTEGER PRIMARY KEY,
                pid TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                sku TEXT DEFAULT '',
                price REAL DEFAULT 0,
                base_price REAL DEFAULT 0,
                has_discount INTEGER DEFAULT 0,
                discount_amount REAL DEFAULT 0,
                valid INTEGER DEFAULT 1,
                url TEXT DEFAULT '',
                image TEXT DEFAULT '',
                shop_name TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_cart_items_pid ON cart_items(pid);
            CREATE INDEX IF NOT EXISTS idx_cart_items_valid ON cart_items(valid);

            -- 2. Bảng cài đặt Giá đáy (Mức giá mong muốn)
            CREATE TABLE IF NOT EXISTS target_prices (
                pid TEXT PRIMARY KEY,
                target_price REAL NOT NULL,
                name TEXT NOT NULL,
                sku TEXT DEFAULT '',
                url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_notified_price REAL DEFAULT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_target_prices_pid ON target_prices(pid);

            -- 3. Bảng lịch sử biến động giá theo thời gian
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pid TEXT NOT NULL,
                price REAL NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_history_pid_time ON price_history(pid, timestamp);

            -- 4. Bảng tóm tắt giỏ hàng (Tổng tiền sau voucher, tạm tính, phí ship)
            CREATE TABLE IF NOT EXISTS cart_summary (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_price TEXT DEFAULT '0₫',
                subtotal TEXT DEFAULT '',
                promotion TEXT DEFAULT '',
                shipping_fee TEXT DEFAULT '',
                item_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 5. Bảng người dùng đăng ký nhận tin báo qua Telegram
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            );

            -- 6. Bảng cấu hình hệ thống
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    # Tự động di chuyển dữ liệu cũ từ JSON sang SQLite nếu lần đầu khởi tạo
    _migrate_legacy_data()


def _migrate_legacy_data() -> None:
    """Tự động chuyển đổi dữ liệu từ các file JSON cũ sang SQLite"""
    try:
        with get_db() as conn:
            # 1. Migrate Subscribers
            cur = conn.execute("SELECT COUNT(*) FROM subscribers")
            if cur.fetchone()[0] == 0 and os.path.exists(LEGACY_SUBS_FILE):
                try:
                    with open(LEGACY_SUBS_FILE, "r", encoding="utf-8") as f:
                        s_data = json.load(f)
                    for chat_id in s_data.get("subscribers", []):
                        conn.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))
                    auto_val = "1" if s_data.get("auto_track_enabled", True) else "0"
                    conn.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('auto_track_enabled', ?)", (auto_val,))
                    logger.info("Đã di chuyển subscribers từ JSON sang SQLite thành công.")
                except Exception as e:
                    logger.warning(f"Lỗi migrate subscribers: {e}")

            # 2. Migrate Price History & Cart Items
            cur = conn.execute("SELECT COUNT(*) FROM cart_items")
            if cur.fetchone()[0] == 0 and os.path.exists(LEGACY_HISTORY_FILE):
                try:
                    with open(LEGACY_HISTORY_FILE, "r", encoding="utf-8") as f:
                        h_data = json.load(f)
                    prods = h_data.get("products", {})
                    stt = 1
                    for pid, p in prods.items():
                        name = p.get("name", "Sản phẩm")
                        sku = p.get("sku", "")
                        cur_p = float(p.get("current_price") or 0)
                        base_p = float(p.get("base_price") or cur_p)
                        val = 1 if p.get("valid", True) else 0
                        url = p.get("url", "")
                        has_disc = 1 if base_p > cur_p else 0
                        disc_amt = base_p - cur_p if has_disc else 0

                        conn.execute("""
                            INSERT OR REPLACE INTO cart_items 
                            (stt, pid, name, sku, price, base_price, has_discount, discount_amount, valid, url)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (stt, pid, name, sku, cur_p, base_p, has_disc, disc_amt, val, url))

                        for rec in p.get("price_history", []):
                            rec_p = float(rec.get("price") or cur_p)
                            rec_t = rec.get("timestamp", datetime.now().isoformat())
                            conn.execute("INSERT INTO price_history (pid, price, timestamp) VALUES (?, ?, ?)", (pid, rec_p, rec_t))

                        stt += 1

                    summary = h_data.get("order_summary", {})
                    if summary:
                        conn.execute("""
                            INSERT OR REPLACE INTO cart_summary (id, total_price, subtotal, promotion, shipping_fee, item_count)
                            VALUES (1, ?, ?, ?, ?, ?)
                        """, (
                            summary.get("Total", "0₫"),
                            summary.get("Subtotal", ""),
                            summary.get("Promotion", ""),
                            summary.get("Shipping Fee", ""),
                            len(prods)
                        ))
                    logger.info("Đã di chuyển giỏ hàng từ price_history.json sang SQLite thành công.")
                except Exception as e:
                    logger.warning(f"Lỗi migrate price_history: {e}")

            # 3. Migrate Target Prices
            cur = conn.execute("SELECT COUNT(*) FROM target_prices")
            if cur.fetchone()[0] == 0 and os.path.exists(LEGACY_TARGET_FILE):
                try:
                    with open(LEGACY_TARGET_FILE, "r", encoding="utf-8") as f:
                        t_data = json.load(f)
                    for pid, item in t_data.items():
                        conn.execute("""
                            INSERT OR REPLACE INTO target_prices 
                            (pid, target_price, name, sku, url, created_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            pid,
                            float(item.get("target_price", 0)),
                            item.get("name", "Sản phẩm"),
                            item.get("sku", ""),
                            item.get("url", ""),
                            item.get("set_at", datetime.now().isoformat())
                        ))
                    logger.info("Đã di chuyển target_prices sang SQLite thành công.")
                except Exception as e:
                    logger.warning(f"Lỗi migrate target_prices: {e}")
    except Exception as e:
        logger.error(f"Lỗi khởi tạo di chuyển dữ liệu: {e}")


# ==============================================================================
# CART & PRODUCT MANAGEMENT
# ==============================================================================

def save_cart_to_db(products: List[Dict[str, Any]], summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Lưu giỏ hàng mới nhất vào SQLite:
    - Đánh số thứ tự (STT 1, 2, 3...) tuần tự cho tất cả mặt hàng hợp lệ (còn hàng).
    - Các mặt hàng hết hàng được xếp tiếp theo.
    - Cập nhật lịch sử biến động giá nếu giá thay đổi.
    - Trả về danh sách sản phẩm kèm STT đã gán chuẩn xác 100%.
    """
    now_iso = datetime.now().isoformat()
    valid_items = [p for p in products if p.get("valid", True)]
    invalid_items = [p for p in products if not p.get("valid", True)]
    ordered_items = valid_items + invalid_items

    with get_db() as conn:
        # Xóa giỏ hàng cũ để cập nhật danh sách mới theo thứ tự hiện tại
        conn.execute("DELETE FROM cart_items")

        updated_products = []
        for idx, p in enumerate(ordered_items, 1):
            name = (p.get("name") or "").strip()
            sku = (p.get("sku") or "").strip()
            price = float(p.get("price") or 0)
            base_price = float(p.get("base_price") or price)
            has_disc = 1 if (p.get("has_discount") or base_price > price) else 0
            disc_amt = float(p.get("discount_amount") or (base_price - price if has_disc else 0))
            is_valid = 1 if p.get("valid", True) else 0
            url = p.get("url", "")
            image = p.get("image", "")
            shop_name = p.get("shop_name", "")

            # Mã hash chuẩn
            from price_tracker import _hash_id
            pid = _hash_id(f"{name} || {sku}")

            conn.execute("""
                INSERT INTO cart_items 
                (stt, pid, name, sku, price, base_price, has_discount, discount_amount, valid, url, image, shop_name, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (idx, pid, name, sku, price, base_price, has_disc, disc_amt, is_valid, url, image, shop_name, now_iso))

            # Ghi nhận lịch sử giá nếu chưa có hoặc có giá mới
            cur = conn.execute("SELECT price FROM price_history WHERE pid = ? ORDER BY id DESC LIMIT 1", (pid,))
            last_rec = cur.fetchone()
            if not last_rec or last_rec["price"] != price:
                conn.execute("INSERT INTO price_history (pid, price, timestamp) VALUES (?, ?, ?)", (pid, price, now_iso))

            p_copy = dict(p)
            p_copy["stt"] = idx
            p_copy["pid"] = pid
            updated_products.append(p_copy)

        # Cập nhật thông tin tổng tiền giỏ hàng
        conn.execute("""
            INSERT OR REPLACE INTO cart_summary (id, total_price, subtotal, promotion, shipping_fee, item_count, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?)
        """, (
            summary.get("Total", "0₫"),
            summary.get("Subtotal", ""),
            summary.get("Promotion", ""),
            summary.get("Shipping Fee", ""),
            len(ordered_items),
            now_iso
        ))

    return updated_products


def get_cart_items_db(valid_only: bool = False) -> List[Dict[str, Any]]:
    """Lấy danh sách sản phẩm trong giỏ hàng sắp xếp theo STT chuẩn xác"""
    conn = get_connection()
    sql = "SELECT * FROM cart_items"
    if valid_only:
        sql += " WHERE valid = 1"
    sql += " ORDER BY stt ASC"

    rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_cart_summary_db() -> Dict[str, Any]:
    """Lấy thông tin tóm tắt đơn hàng (Giá cuối, voucher, ship)"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM cart_summary WHERE id = 1").fetchone()
    if row:
        return {
            "Total": row["total_price"],
            "Subtotal": row["subtotal"],
            "Promotion": row["promotion"],
            "Shipping Fee": row["shipping_fee"],
            "item_count": row["item_count"],
            "updated_at": row["updated_at"]
        }
    return {"Total": "0₫", "item_count": 0}


def find_product_by_stt_or_query(query: str) -> Optional[Dict[str, Any]]:
    """
    Tìm sản phẩm theo:
    1. Số thứ tự (STT: 1, 2, 3...) - Tuyệt đối không bao giờ nhầm lẫn.
    2. Từ khóa trong tên hoặc phân loại SKU.
    """
    if not query:
        return None

    conn = get_connection()
    cleaned = query.strip()

    # 1. Tìm theo STT chính xác
    if cleaned.isdigit():
        stt = int(cleaned)
        row = conn.execute("""
            SELECT c.*, t.target_price 
            FROM cart_items c 
            LEFT JOIN target_prices t ON c.pid = t.pid 
            WHERE c.stt = ?
        """, (stt,)).fetchone()
        if row:
            return dict(row)

    # 2. Tìm theo từ khóa trong tên hoặc SKU (không phân biệt hoa thường)
    term = f"%{cleaned}%"
    row = conn.execute("""
        SELECT c.*, t.target_price 
        FROM cart_items c 
        LEFT JOIN target_prices t ON c.pid = t.pid 
        WHERE c.name LIKE ? OR c.sku LIKE ?
        ORDER BY c.stt ASC 
        LIMIT 1
    """, (term, term)).fetchone()

    if row:
        return dict(row)

    return None


# ==============================================================================
# TARGET PRICE (GIÁ ĐÁY) MANAGEMENT
# ==============================================================================

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

    # Triệu: 1.5tr, 1.5m, 2tr
    m_tr = re.match(r'^([\d.,]+)\s*(?:tr|trieu|triệu|m)$', cleaned)
    if m_tr:
        num_str = m_tr.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000_000
        except ValueError:
            pass

    # Nghìn: 100k, 150.5k
    m_k = re.match(r'^([\d.,]+)\s*k$', cleaned)
    if m_k:
        num_str = m_k.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000
        except ValueError:
            pass

    # Số thông thường: 100.000, 100000, 100,000
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


def set_target_price_db(pid: str, name: str, sku: str, target_price: float, url: str = "") -> Dict[str, Any]:
    """Đặt mức Giá đáy mong muốn cho 1 sản phẩm"""
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO target_prices 
            (pid, target_price, name, sku, url, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (pid, float(target_price), name, sku, url, now_iso))

    return {
        "pid": pid,
        "name": name,
        "sku": sku,
        "target_price": float(target_price),
        "url": url,
        "created_at": now_iso
    }


def get_target_price_db(pid: str) -> Optional[float]:
    """Lấy mức Giá đáy của sản phẩm nếu có"""
    conn = get_connection()
    row = conn.execute("SELECT target_price FROM target_prices WHERE pid = ?", (pid,)).fetchone()
    if row:
        return float(row["target_price"])
    return None


def get_all_target_prices_db() -> List[Dict[str, Any]]:
    """
    Lấy danh sách toàn bộ các sản phẩm đã cài đặt Giá đáy:
    Luôn kèm theo Số thứ tự STT và Giá hiện tại trong giỏ hàng.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT 
            t.pid,
            t.target_price,
            COALESCE(c.name, t.name) as name,
            COALESCE(c.sku, t.sku) as sku,
            COALESCE(c.url, t.url) as url,
            c.stt,
            c.price as current_price,
            t.created_at
        FROM target_prices t
        LEFT JOIN cart_items c ON t.pid = c.pid
        ORDER BY CASE WHEN c.stt IS NULL THEN 9999 ELSE c.stt END ASC
    """).fetchall()

    return [dict(r) for r in rows]


def remove_target_price_db(pid: str) -> bool:
    """Xóa mức Giá đáy của 1 sản phẩm"""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM target_prices WHERE pid = ?", (pid,))
        return cur.rowcount > 0


def clear_all_target_prices_db() -> int:
    """Xóa toàn bộ mức Giá đáy đã cài đặt"""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM target_prices")
        return cur.rowcount


def should_notify_price_change_db(pid: str, old_price: Optional[float], new_price: Optional[float]) -> Tuple[bool, Optional[float]]:
    """
    Kiểm tra điều kiện thông báo giá:
    - Nếu KHÔNG đặt giá đáy: Luôn gửi thông báo khi có biến động giá.
    - Nếu CÓ đặt giá đáy: Chỉ gửi thông báo khi giá giảm xuống THẤP HƠN HOẶC BẰNG (<=) giá đáy.
    """
    target = get_target_price_db(pid)
    if target is None:
        return True, None

    if new_price is None:
        return False, target

    # Giá giảm xuống chạm hoặc thấp hơn giá đáy
    is_price_drop = (old_price is not None and new_price < old_price)
    is_at_or_below_target = (new_price <= target)

    if is_price_drop and is_at_or_below_target:
        return True, target

    # Giá cũ cao hơn target và giá mới rơi xuống <= target
    if old_price is not None and old_price > target and is_at_or_below_target:
        return True, target

    return False, target


# ==============================================================================
# SUBSCRIBER MANAGEMENT
# ==============================================================================

def get_subscribers_db() -> List[int]:
    """Lấy danh sách Chat ID nhận thông báo"""
    conn = get_connection()
    rows = conn.execute("SELECT chat_id FROM subscribers WHERE is_active = 1").fetchall()
    return [int(r["chat_id"]) for r in rows]


def add_subscriber_db(chat_id: int) -> bool:
    """Thêm người nhận thông báo"""
    with get_db() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO subscribers (chat_id, is_active) VALUES (?, 1)", (chat_id,))
        if cur.rowcount == 0:
            conn.execute("UPDATE subscribers SET is_active = 1 WHERE chat_id = ?", (chat_id,))
        return True


def remove_subscriber_db(chat_id: int) -> bool:
    """Xóa người nhận thông báo"""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        return cur.rowcount > 0


def is_auto_track_enabled_db() -> bool:
    """Kiểm tra trạng thái quét tự động ngầm"""
    conn = get_connection()
    row = conn.execute("SELECT value FROM bot_settings WHERE key = 'auto_track_enabled'").fetchone()
    if row:
        return row["value"] == "1"
    return True


def set_auto_track_enabled_db(enabled: bool) -> None:
    """Bật/tắt quét tự động ngầm"""
    val = "1" if enabled else "0"
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('auto_track_enabled', ?)", (val,))


# Khởi tạo database tự động khi load module
init_db()
