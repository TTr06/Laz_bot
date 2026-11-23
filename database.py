"""
Database Module for LazBot (SQLite Engine)
Tối ưu hiệu năng, lưu trữ đồng bộ giỏ hàng, lịch sử giá và mức giá đáy (Target Price).
Đảm bảo Số thứ tự (STT 1, 2, 3...) luôn chuẩn xác, không bị xáo trộn khi thêm/sửa giá đáy.
"""

import hashlib
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


def _hash_id(raw_str: str) -> str:
    """Tạo mã định danh duy nhất (MD5 16 ký tự) từ Tên sản phẩm + Phân loại SKU"""
    return hashlib.md5(raw_str.encode("utf-8")).hexdigest()[:16]

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
                last_notified_price REAL DEFAULT NULL,
                is_active INTEGER DEFAULT 1
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

        # Di chuyển schema tự động nếu phiên bản cũ chưa có cột is_active
        try:
            conn.execute("ALTER TABLE target_prices ADD COLUMN is_active INTEGER DEFAULT 1")
        except Exception:
            pass

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
                    if t_data:
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

        # Tự động cập nhật trạng thái theo dõi trong database:
        # Sản phẩm còn trong giỏ -> is_active = 1 (Kích hoạt)
        # Sản phẩm đã bị xóa khỏi giỏ -> is_active = 0 (Vô hiệu hóa)
        conn.execute("UPDATE target_prices SET is_active = 1 WHERE pid IN (SELECT pid FROM cart_items)")
        conn.execute("UPDATE target_prices SET is_active = 0 WHERE pid NOT IN (SELECT pid FROM cart_items)")

    return updated_products


def update_product_price_db(pid: str, new_price: float) -> bool:
    """
    Cập nhật giá hiện tại của sản phẩm vào database (cart_items và price_history),
    đảm bảo luôn lưu giá mới nhất bất kể giá mới cao hơn hay thấp hơn mức giá đáy (target_price).
    """
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        # Cập nhật giá hiện tại trong cart_items
        cur = conn.execute("""
            UPDATE cart_items 
            SET price = ?, updated_at = ? 
            WHERE pid = ?
        """, (float(new_price), now_iso, pid))

        # Ghi nhận lịch sử giá nếu giá thay đổi
        last_rec = conn.execute("SELECT price FROM price_history WHERE pid = ? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
        if not last_rec or last_rec["price"] != float(new_price):
            conn.execute("INSERT INTO price_history (pid, price, timestamp) VALUES (?, ?, ?)", (pid, float(new_price), now_iso))

        return cur.rowcount > 0


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
    - 1tr5, 2tr2 -> 1500000, 2200000
    - 1.5tr, 1,5m, 2tr, 2 triệu -> 1500000, 2000000
    - 1k5, 2k2 -> 1500, 2200
    - 100 ngàn, 100 nghìn, 100 ngan -> 100000
    - 100.000, 100,000, 100000 -> 100000
    - 85 -> 85000 (nếu số < 1000 thì quy ước nghìn)
    - 0, off, del, xoa -> 0.0 (tín hiệu xóa)
    """
    if not text:
        return None
    cleaned = text.strip().lower()
    cleaned = cleaned.replace("₫", "").replace("đ", "").replace("vnd", "").strip()

    if cleaned in ("0", "off", "del", "xoa", "xóa", "huy", "hủy"):
        return 0.0

    # Phối hợp triệu: 1tr5, 2tr25, 1m5
    m_split_tr = re.match(r'^(\d+)\s*(?:tr|trieu|triệu|m)\s*(\d+)$', cleaned)
    if m_split_tr:
        try:
            return float(f"{m_split_tr.group(1)}.{m_split_tr.group(2)}") * 1_000_000
        except ValueError:
            pass

    # Phối hợp nghìn: 1k5, 2k2
    m_split_k = re.match(r'^(\d+)\s*k\s*(\d+)$', cleaned)
    if m_split_k:
        try:
            return float(f"{m_split_k.group(1)}.{m_split_k.group(2)}") * 1_000
        except ValueError:
            pass

    # Triệu: 1.5tr, 1,5m, 2tr, 2 triệu
    m_tr = re.match(r'^([\d.,]+)\s*(?:tr|trieu|triệu|m)$', cleaned)
    if m_tr:
        num_str = m_tr.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000_000
        except ValueError:
            pass

    # Nghìn: 100k, 150.5k, 100 ngàn, 100 nghìn
    m_k = re.match(r'^([\d.,]+)\s*(?:k|ngàn|nghìn|ngan|nghin)$', cleaned)
    if m_k:
        num_str = m_k.group(1).replace(",", ".")
        try:
            return float(num_str) * 1_000
        except ValueError:
            pass

    # Số thông thường: 100.000, 100,000, 100000 hoặc số trần (85 -> 85000)
    m_plain = re.match(r'^([\d.,]+)$', cleaned)
    if m_plain:
        raw_num = m_plain.group(1)
        num_clean = re.sub(r'[^\d]', '', raw_num)
        if num_clean:
            try:
                val = float(num_clean)
                if 0 < val < 1000 and "." not in raw_num and "," not in raw_num:
                    val = val * 1000
                return val
            except ValueError:
                pass

    return None


def parse_quick_del_input(text: str) -> Optional[Tuple[str, Optional[str]]]:
    """
    Nhận diện lệnh xóa giá đáy nhanh:
    - 'xoa all', 'del all', 'xóa all', 'xoa tat ca', 'xóa tất cả' -> ('ALL', None)
    - 'xoa 1', 'del 1', 'xóa 1', 'del #1', 'xoa sp 1', 'xoa stt 1' -> ('SINGLE', '1')
    - '1 0', '1 off', '1 xoa', '1 xóa', '1 del' -> ('SINGLE', '1')
    - 'xoa ugreen' -> ('SINGLE', 'ugreen')
    """
    raw = text.strip()
    if not raw or len(raw) > 100 or "\n" in raw:
        return None

    cleaned = raw.lower()

    # 1. Xóa toàn bộ
    all_pattern = r'^(?:xoa|xóa|del|clear|huy|hủy)\s+(?:all|tat\s*ca|tất\s*cả|toan\s*bo|toàn\s*bộ)$'
    if re.match(all_pattern, cleaned):
        return ("ALL", None)

    # 2. Xóa theo tiền tố: xoa 1, del #2, xóa sp 3, xoa ugreen
    m_del_prefix = re.match(r'^(?:xoa|xóa|del|clear|huy|hủy|remove)\s+(?:sp\s*|stt\s*|#)?(.+)$', cleaned)
    if m_del_prefix:
        target_query = m_del_prefix.group(1).strip()
        if target_query:
            return ("SINGLE", target_query)

    # 3. Hậu tố xóa: '1 0', '1 off', 'sp 1 0', '#1: 0', '2 xoa', '1=off'
    m_suffix = re.match(r'^(?:sp\s*|stt\s*|#)?(\d+)\s*(?:[:=-]\s*)?(?:0|off|xoa|xóa|del|huy|hủy|none)$', cleaned)
    if m_suffix:
        return ("SINGLE", m_suffix.group(1).strip())

    return None


def _parse_single_quick_set_line(raw: str) -> Optional[Tuple[str, float, bool]]:
    """
    Phân tích 1 dòng hoặc 1 mệnh đề đặt giá nhanh.
    Trả về (query_str, target_price, is_explicit) nếu hợp lệ.
    """
    if not raw or "\n" in raw:
        return None
    s = raw.strip()

    # Bỏ qua nếu là lệnh slash hoặc chuỗi URL
    if s.startswith("/") and not re.match(r'^/setprice\b', s, flags=re.IGNORECASE):
        return None
    if "http://" in s or "https://" in s:
        return None

    # Kiểm tra tiền tố chỉ định rõ ràng: set, setprice, cài, giá đáy...
    is_explicit = False
    prefix_pattern = r'^(?:(?:/)?(?:setprice|set|cài\s*đặt|cai\s*dat|cài|cai|giá\s*đáy|gia\s*day|giá|gia|đáy|day))\s+'
    m_pref = re.match(prefix_pattern, s, flags=re.IGNORECASE)
    if m_pref:
        is_explicit = True
        s = s[m_pref.end():].strip()

    # Kiểm tra dấu phân cách rõ ràng: ':', '=', '->', '=>', hoặc '-' (chỉ khi có khoảng trắng xung quanh hoặc dạng stt-gia)
    m_delim = re.split(r'\s*(?:[:=]|->|=>)\s*', s, maxsplit=1)
    if len(m_delim) == 2 and m_delim[0].strip() and m_delim[1].strip():
        cand_query, cand_price = m_delim[0].strip(), m_delim[1].strip()
        price_val = parse_user_price(cand_price)
        if price_val is not None and price_val > 0:
            q_clean = re.sub(r'^(?:sp\s*|stt\s*|#)\s*', '', cand_query, flags=re.IGNORECASE).strip()
            return (q_clean or cand_query, price_val, True)

    # Thử phân cách bằng dấu gạch ngang: '1 - 100k', '1-100k'
    m_dash = re.match(r'^(?:sp\s*|stt\s*|#)?(\d+)\s*-\s*(.+)$', s, flags=re.IGNORECASE)
    if m_dash:
        cand_query, cand_price = m_dash.group(1).strip(), m_dash.group(2).strip()
        price_val = parse_user_price(cand_price)
        if price_val is not None and price_val > 0:
            return (cand_query, price_val, True)

    # Tách từ theo khoảng trắng
    tokens = s.split()
    if len(tokens) < 2:
        return None

    # Thử 2 từ cuối làm giá (ví dụ: '1.5 triệu', '150 ngàn') - chỉ khi từ cuối là đơn vị tiền tệ
    price_val = None
    query_str = None
    PRICE_UNITS = ("tr", "trieu", "triệu", "m", "k", "ngàn", "nghìn", "ngan", "nghin", "vnd", "đ")
    if len(tokens) >= 3 and tokens[-1].lower() in PRICE_UNITS:
        cand_p2 = f"{tokens[-2]} {tokens[-1]}"
        p2 = parse_user_price(cand_p2)
        if p2 is not None and p2 > 0:
            price_val = p2
            query_str = " ".join(tokens[:-2])

    # Nếu không được, thử 1 từ cuối làm giá (ví dụ: '100k', '45k', '1tr5', '200.000')
    if price_val is None:
        cand_p1 = tokens[-1]
        p1 = parse_user_price(cand_p1)
        if p1 is not None and p1 > 0:
            price_val = p1
            query_str = " ".join(tokens[:-1])

    if price_val is None or not query_str:
        return None

    # Làm sạch query nếu có tiền tố sp, stt, #
    m_sp = re.match(r'^(?:sp\s*|stt\s*|#)\s*(.*)$', query_str, flags=re.IGNORECASE)
    if m_sp:
        is_explicit = True
        query_str = m_sp.group(1).strip() or query_str

    if query_str.isdigit():
        is_explicit = True

    return (query_str, price_val, is_explicit)


def parse_quick_setprice_input(text: str) -> Tuple[List[Tuple[Dict[str, Any], float]], List[str]]:
    """
    Phân tích chuỗi tin nhắn đặt giá nhanh (hỗ trợ cả đơn lẻ và hàng loạt):
    - Đơn lẻ: '1 100k', '#2 45k', 'sp1: 1.5tr', 'ugreen 50k'
    - Hàng loạt nhiều dòng:
        1 100k
        2 50k
        3 1.5tr
    - Hàng loạt ngăn cách bởi dấu phẩy/chấm phẩy:
        1 100k, 2 50k, 3 1.5tr

    Trả về:
    (matched_items, unmatched_queries)
    - matched_items: Danh sách tuple (product_dict, target_price)
    - unmatched_queries: Danh sách các truy vấn tường minh nhưng không tìm thấy SP
    """
    if not text:
        return [], []

    raw_text = text.strip()
    batch_delim_pattern = r'[,;]\s*(?=(?:(?:sp\s*|stt\s*|#)\s*\d+|\d+\s*[:=\s-]|[a-zA-Z0-9_\u00C0-\u024F\u1EA0-\u1EF9]+\s*[:=]))'

    # Phân tách dòng hoặc danh sách hàng loạt
    if "\n" in raw_text:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    elif re.search(batch_delim_pattern, raw_text, flags=re.IGNORECASE):
        lines = [part.strip() for part in re.split(batch_delim_pattern, raw_text, flags=re.IGNORECASE) if part.strip()]
    else:
        # Xử lý đơn lẻ
        single_res = _parse_single_quick_set_line(raw_text)
        if single_res:
            q_str, p_val, is_exp = single_res
            prod = find_product_by_stt_or_query(q_str)
            if prod:
                return [(prod, p_val)], []
            elif is_exp:
                return [], [q_str]
        return [], []

    matched_items: List[Tuple[Dict[str, Any], float]] = []
    unmatched_queries: List[str] = []
    seen_pids = set()

    for line in lines:
        parsed = _parse_single_quick_set_line(line)
        if not parsed:
            continue
        q_str, p_val, is_exp = parsed
        prod = find_product_by_stt_or_query(q_str)
        if prod:
            pid = prod["pid"]
            if pid not in seen_pids:
                seen_pids.add(pid)
                matched_items.append((prod, p_val))
        elif is_exp:
            unmatched_queries.append(q_str)

    return matched_items, unmatched_queries


def set_target_price_db(pid: str, name: str, sku: str, target_price: float, url: str = "") -> Dict[str, Any]:
    """Đặt mức Giá đáy mong muốn cho 1 sản phẩm"""
    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO target_prices 
            (pid, target_price, name, sku, url, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
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


def get_all_target_prices_db(active_only: bool = False) -> List[Dict[str, Any]]:
    """
    Lấy danh sách sản phẩm đã cài đặt Giá đáy:
    - Kèm STT, Giá hiện tại, trạng thái kích hoạt is_active.
    - active_only: Chỉ lấy các sản phẩm đang có trong giỏ hàng.
    """
    conn = get_connection()
    sql = """
        SELECT 
            t.pid,
            t.target_price,
            COALESCE(c.name, t.name) as name,
            COALESCE(c.sku, t.sku) as sku,
            COALESCE(c.url, t.url) as url,
            c.stt,
            c.price as current_price,
            c.valid as in_cart_valid,
            COALESCE(t.is_active, 1) as is_active,
            t.created_at
        FROM target_prices t
        LEFT JOIN cart_items c ON t.pid = c.pid
    """
    if active_only:
        sql += " WHERE COALESCE(t.is_active, 1) = 1 AND c.stt IS NOT NULL"
    sql += """
        ORDER BY 
            CASE WHEN COALESCE(t.is_active, 1) = 1 AND c.stt IS NOT NULL THEN 0 ELSE 1 END,
            CASE WHEN c.stt IS NULL THEN 9999 ELSE c.stt END ASC
    """
    rows = conn.execute(sql).fetchall()
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
    Kiểm tra điều kiện gửi thông báo biến động giá đến người dùng:
    - Sản phẩm đã bị vô hiệu hóa (không còn trong giỏ): KHÔNG gửi thông báo.
    - Nếu KHÔNG đặt giá đáy: Luôn gửi cảnh báo khi giá thay đổi.
    - Nếu CÓ đặt giá đáy: Chỉ gửi cảnh báo khi giá hiện tại <= giá đáy.
    """
    conn = get_connection()
    row = conn.execute("SELECT target_price, COALESCE(is_active, 1) as is_active FROM target_prices WHERE pid = ?", (pid,)).fetchone()
    if row:
        if row["is_active"] == 0:
            return False, None
        target = float(row["target_price"])
        if new_price is None:
            return False, target
        if new_price <= target:
            if old_price is None or new_price < old_price or old_price > target:
                return True, target
        return False, target

    return True, None


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
