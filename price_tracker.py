"""
Lazada Cart Price Tracker
Theo dõi giá tất cả sản phẩm & tất cả phân loại (SKU) trong giỏ hàng Lazada:
- TUYỆT ĐỐI KHÔNG bấm vào trang thanh toán (checkout).
- Chỉ thao tác tại trang giỏ hàng (https://cart.lazada.vn/cart).
- Click nút 'Chọn tất cả' trong giỏ để kích hoạt voucher/giảm giá tự động.
- Theo dõi độc lập từng phân loại (màu sắc, cấu hình, loại máy...).
- Phát hiện biến động giá từng món và biến động tổng tiền giỏ hàng.
- Báo động khi Cookie hết hạn.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from anti_detect import (
    create_stealth_driver,
    get_or_create_driver,
    close_shared_driver,
    load_cookies,
    save_cookies,
    safe_quit,
    safe_get,
    COOKIES_FILE,
)
from target_price_manager import should_notify_price_change, get_target_price

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICE_HISTORY_FILE = os.path.join(BASE_DIR, "price_history.json")
CART_URL = "https://cart.lazada.vn/cart"


def load_price_history() -> dict:
    if os.path.exists(PRICE_HISTORY_FILE):
        try:
            with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"products": {}, "last_check": None, "order_summary": None}


def save_price_history(data: dict) -> None:
    with open(PRICE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_price(price_text: Any) -> Optional[float]:
    if price_text is None:
        return None
    cleaned = re.sub(r'[^\d.,]', '', str(price_text))
    cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return None


def _hash_id(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def scrape_cart(headless: bool = True, keep_alive: bool = False) -> Dict[str, Any]:
    """
    Truy cập giỏ hàng Lazada, tick 'Chọn tất cả' ngay tại giỏ hàng và đọc giá thực tế sau giảm.
    Cam kết: KHÔNG BAO GIỜ bấm vào nút thanh toán (CONFIRM CART / Checkout).
    Tối ưu hóa:
    - Chặn ảnh & web fonts giúp tải trang siêu tốc.
    - Polling thông minh (Smart Polling) thay vì sleep cứng, phản hồi tức thì khi dữ liệu xuất hiện.
    - Cuộn trang tức thời bằng JavaScript.
    - Tùy chọn keep_alive giữ phiên trình duyệt để quét tức thì (< 2s).
    """
    if not os.path.exists(COOKIES_FILE):
        return {
            "status": "need_login",
            "message": "Chưa có cookie. Hãy nạp cookie Lazada qua file cookie.json hoặc lệnh /cookie",
            "products": [],
            "summary": {}
        }

    driver = None
    try:
        if keep_alive:
            driver = get_or_create_driver(headless=headless)
        else:
            driver = create_stealth_driver(headless=headless)
            if not load_cookies(driver):
                return {
                    "status": "need_login",
                    "message": "Không nạp được cookie vào trình duyệt. Cookie có thể bị lỗi hoặc chưa đăng nhập.",
                    "products": [],
                    "summary": {}
                }

        # 1. Truy cập trang giỏ hàng (áp dụng safe_get chống timeout)
        safe_get(driver, CART_URL, timeout=30)

        # Chờ thông minh: kiểm tra xem __initData__ hoặc DOM giỏ hàng đã xuất hiện chưa (tối đa 3.5s, tick mỗi 100ms)
        for _ in range(35):
            ready = driver.execute_script("""
                return Boolean(
                    (window.__initData__ && window.__initData__.module && window.__initData__.module.data) ||
                    document.querySelector('.list-header-checkbox, .checkout-summary, .cart-empty')
                );
            """)
            if ready:
                break
            time.sleep(0.1)

        cur_url = driver.current_url.lower()
        if "member.lazada.vn" in cur_url or "login" in cur_url:
            if keep_alive:
                close_shared_driver()
            return {
                "status": "need_login",
                "message": "Cookie đã hết hạn hoặc không hợp lệ. Vui lòng cập nhật cookie mới.",
                "products": [],
                "summary": {}
            }

        # Kiểm tra xem có đang ở trạng thái phiên khách (chưa đăng nhập / cookie hết hạn) không
        auth_status = driver.execute_script("""
            var bodyText = document.body ? document.body.innerText : '';
            var hasLoginBtn = /\\b(LOGIN|SIGNUP|Sign in|Sign up)\\b/i.test(bodyText);
            var hasAccount = /'s Account|Tài khoản của|Thông tin tài khoản/i.test(bodyText);
            var initData = window.__initData__;
            var hasModules = initData && initData.module && initData.module.data && Object.keys(initData.module.data).length > 0;
            return {
                hasLoginBtn: hasLoginBtn,
                hasAccount: hasAccount,
                hasModules: hasModules
            };
        """)

        if auth_status and auth_status.get("hasLoginBtn") and not auth_status.get("hasAccount") and not auth_status.get("hasModules"):
            if keep_alive:
                close_shared_driver()
            return {
                "status": "need_login",
                "message": "Phiên đăng nhập Lazada đã hết hạn (chưa đăng nhập). Vui lòng cập nhật cookie mới bằng /cookie.",
                "products": [],
                "summary": {}
            }

        # 2. Cuộn trang siêu tốc bằng JavaScript để kích hoạt Lazy-load nạp 100% tất cả SKU
        try:
            driver.execute_script("""
                window.scrollTo(0, document.body.scrollHeight || 3000);
                setTimeout(function() { window.scrollTo(0, 0); }, 150);
            """)
            time.sleep(0.25)
        except Exception:
            pass

        # 3. CHỈ CLICK NÚT 'CHỌN TẤT CẢ' TRÊN GIAO DIỆN GIỎ HÀNG
        # TUYỆT ĐỐI KHÔNG CLICK VÀO NÚT THANH TOÁN (CHECKOUT)!
        driver.execute_script("""
            var selectAllCheckbox = document.querySelector('.list-header-checkbox input, .checkbox-wrap label, .list-header-checkbox, .checkbox-wrap input');
            if (selectAllCheckbox) {
                selectAllCheckbox.click();
            }
        """)

        # 4. Chờ thông minh số tiền summary cập nhật (tối đa 1.5s, tick mỗi 100ms)
        for _ in range(15):
            summary_txt = driver.execute_script("""
                var el = document.querySelector('.checkout-summary, .summary-section');
                return el ? el.innerText : '';
            """)
            if summary_txt and "0 items" not in summary_txt:
                break
            time.sleep(0.1)

        # 5. Đọc dữ liệu từng sản phẩm & từng phân loại và Giá Cuối Cùng ngay tại giỏ
        products, summary_data = _extract_cart_and_summary(driver)

        if not products:
            if not auth_status.get("hasModules"):
                if keep_alive:
                    close_shared_driver()
                return {
                    "status": "need_login",
                    "message": "Không tải được giỏ hàng cá nhân. Cookie phiên đăng nhập có thể đã hết hạn.",
                    "products": [],
                    "summary": {}
                }
            return {
                "status": "empty",
                "message": "Giỏ hàng hiện đang trống.",
                "products": [],
                "summary": {}
            }

        return {
            "status": "ok",
            "message": f"Đã chọn tất cả và đọc giá {len(products)} phân loại sản phẩm trong giỏ hàng.",
            "products": products,
            "summary": summary_data
        }

    except Exception as e:
        if keep_alive:
            close_shared_driver()
        return {
            "status": "error",
            "message": f"Lỗi khi đọc giỏ hàng: {e}",
            "products": [],
            "summary": {}
        }
    finally:
        if not keep_alive:
            safe_quit(driver)


def _extract_cart_and_summary(driver) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    products = []
    summary_data = {}

    # Trích xuất dữ liệu sản phẩm từ window.__initData__
    try:
        init_data = driver.execute_script("return window.__initData__;")
        if init_data and isinstance(init_data, dict):
            mod_data = init_data.get("module", {}).get("data", {})
            for key, val in mod_data.items():
                if val.get("tag") == "item":
                    fields = val.get("fields", {})
                    title = fields.get("title", "").strip()
                    if not title:
                        continue

                    valid = bool(fields.get("valid", True))
                    sku_info = fields.get("sku", {}) or fields.get("skuInfo", {})
                    sku_text = sku_info.get("skuText", "")
                    url = fields.get("url") or fields.get("itemUrl") or ""
                    if url:
                        if url.startswith("//"):
                            url = "https:" + url
                        url = re.sub(r'lazada\.vn/+', 'lazada.vn/', url)

                    price_info = fields.get("price", {}) or {}
                    base_price = parse_price(price_info.get("price") or price_info.get("currentPrice"))

                    discount_info = fields.get("discountPrice") or {}
                    discount_price = None
                    if discount_info:
                        discount_price = parse_price(discount_info.get("priceAmtValue") or discount_info.get("price"))

                    real_price = discount_price if (discount_price is not None and discount_price > 0) else base_price

                    products.append({
                        "name": title,
                        "sku": sku_text,
                        "valid": valid,
                        "base_price": base_price,
                        "discount_price": discount_price,
                        "price": real_price,
                        "has_discount": bool(discount_price and discount_price < base_price),
                        "discount_amount": (base_price - discount_price) if (discount_price and base_price) else 0,
                        "url": url,
                        "timestamp": datetime.now().isoformat()
                    })

    except Exception as e:
        print(f"[!] Lỗi trích xuất __initData__: {e}")

    # Đọc phần tóm tắt đơn hàng (Order Summary) trực tiếp từ giao diện giỏ hàng
    try:
        summary_raw_text = driver.execute_script("""
            var el = document.querySelector('.checkout-summary, .summary-section');
            return el ? el.innerText : '';
        """)
        if summary_raw_text:
            m_total = re.search(r'Total[\s\t]+(₫?\s*[\d\.,]+)', summary_raw_text, re.IGNORECASE)
            if m_total:
                summary_data['Total'] = m_total.group(1).strip()

            m_sub = re.search(r'Subtotal[^\n]*\n\s*(₫?\s*[\d\.,]+)', summary_raw_text, re.IGNORECASE)
            if m_sub:
                summary_data['Subtotal'] = m_sub.group(1).strip()

            m_promo = re.search(r'Promotion[^\n]*\n\s*(-?₫?\s*[\d\.,]+)', summary_raw_text, re.IGNORECASE)
            if m_promo:
                summary_data['Promotion'] = m_promo.group(1).strip()

            m_ship = re.search(r'Shipping Fee[^\n]*\n\s*([^\n]+)', summary_raw_text, re.IGNORECASE)
            if m_ship:
                summary_data['Shipping Fee'] = m_ship.group(1).strip()
    except Exception as e:
        print(f"[!] Lỗi đọc summary text: {e}")

    return products, summary_data


def track_prices(headless: bool = True, keep_driver: bool = False) -> dict:
    """
    Theo dõi biến động giá thực tế của TẤT CẢ sản phẩm và TẤT CẢ phân loại (SKU).
    """
    scrape_res = scrape_cart(headless=headless, keep_alive=keep_driver)
    if scrape_res["status"] != "ok":
        return scrape_res

    products = scrape_res["products"]
    summary = scrape_res["summary"]
    history = load_price_history()
    now = datetime.now().isoformat()
    changes = []

    # So sánh từng sản phẩm và từng phân loại
    for p in products:
        name = p["name"]
        sku = p.get("sku", "")
        curr_price = p["price"]
        curr_valid = p.get("valid", True)
        # Khóa định danh duy nhất cho từng phân loại của từng sản phẩm
        pid = _hash_id(f"{name} || {sku}")

        if pid in history["products"]:
            prod_entry = history["products"][pid]
            old_price = prod_entry.get("current_price")
            old_valid = prod_entry.get("valid", True)

            # 1. Phát hiện thay đổi giá (kiểm tra điều kiện giá mục tiêu nếu có)
            if old_price and curr_price and old_price != curr_price:
                diff = curr_price - old_price
                pct = (diff / old_price) * 100
                should_notify, target_price = should_notify_price_change(pid, old_price, curr_price)
                if should_notify:
                    changes.append({
                        "type": "PRICE_CHANGE",
                        "name": name,
                        "sku": sku,
                        "old_price": old_price,
                        "new_price": curr_price,
                        "diff": diff,
                        "diff_pct": round(pct, 2),
                        "direction": "GIẢM" if diff < 0 else "TĂNG",
                        "url": p.get("url", ""),
                        "target_price": target_price,
                        "reached_target": bool(target_price and curr_price <= target_price)
                    })
                prod_entry["price_history"].append({"price": curr_price, "timestamp": now})
                prod_entry["current_price"] = curr_price

            # 2. Phát hiện thay đổi trạng thái tồn kho (Hết hàng / Có hàng lại)
            if old_valid != curr_valid:
                changes.append({
                    "type": "STOCK_CHANGE",
                    "name": name,
                    "sku": sku,
                    "status": "CÓ HÀNG LẠI" if curr_valid else "HẾT HÀNG",
                    "price": curr_price,
                    "url": p.get("url", "")
                })
                prod_entry["valid"] = curr_valid

            prod_entry["last_check"] = now
            prod_entry["sku"] = sku
        else:
            # Sản phẩm / phân loại mới được thêm vào giỏ
            history["products"][pid] = {
                "name": name,
                "sku": sku,
                "valid": curr_valid,
                "current_price": curr_price,
                "base_price": p.get("base_price"),
                "url": p.get("url", ""),
                "first_seen": now,
                "last_check": now,
                "price_history": [{"price": curr_price, "timestamp": now}]
            }

    # 3. Phát hiện thay đổi Tổng thanh toán toàn giỏ hàng
    old_summary = history.get("order_summary") or {}
    total_change = None
    if old_summary and summary:
        old_total_str = old_summary.get("Total")
        new_total_str = summary.get("Total")
        if old_total_str and new_total_str and old_total_str != new_total_str:
            old_num = parse_price(old_total_str)
            new_num = parse_price(new_total_str)
            if old_num and new_num:
                diff_total = new_num - old_num
                total_change = {
                    "old_total": old_total_str,
                    "new_total": new_total_str,
                    "diff": diff_total,
                    "direction": "GIẢM" if diff_total < 0 else "TĂNG"
                }

    history["last_check"] = now
    history["order_summary"] = summary
    save_price_history(history)

    return {
        "status": "ok",
        "total_products": len(products),
        "products": products,
        "summary": summary,
        "changes": changes,
        "total_change": total_change,
        "timestamp": now
    }


def format_cart_messages(products: List[dict], summary: dict) -> List[str]:
    """
    Format danh sách sản phẩm và tổng tiền, tự động chia thành nhiều tin nhắn nếu vượt giới hạn ký tự Telegram.
    ĐẢM BẢO HIỂN THỊ ĐẦY ĐỦ 100% TẤT CẢ SẢN PHẨM VÀ TẤT CẢ PHÂN LOẠI (SKU).
    """
    messages = []
    current_lines = []

    valid_items = [p for p in products if p.get("valid", True)]
    invalid_items = [p for p in products if not p.get("valid", True)]
    total_count = len(products)

    # 1. Header & Order Summary (Chỉ hiển thị ở đầu tin nhắn đầu tiên)
    current_lines.append(f"🛒 <b>GIỎ HÀNG LAZADA ({total_count} SẢN PHẨM & PHÂN LOẠI):</b>\n")

    if summary and "Total" in summary:
        current_lines.append(f"🔥 <b>GIÁ CUỐI CÙNG TOÀN GIỎ:</b> <code>{summary['Total']}</code>")
        sub = summary.get("Subtotal")
        promo = summary.get("Promotion")
        ship = summary.get("Shipping Fee")
        details = []
        if sub: details.append(f"Tạm tính: {sub}")
        if promo: details.append(f"Voucher giảm: {promo}")
        if ship: details.append(f"Ship: {ship}")
        if details:
            current_lines.append(f"ℹ️ <i>({', '.join(details)})</i>")
        current_lines.append("━━━━━━━━━━━━━━━━━━━━\n")

    current_lines.append("📦 <b>Chi tiết tất cả mặt hàng & phân loại:</b>")

    # Ước lượng độ dài ký tự
    current_char_count = sum(len(line) + 2 for line in current_lines)

    for i, p in enumerate(valid_items, 1):
        name = p.get("name", "").strip()
        # Hiển thị tên rõ ràng (tối đa 75 ký tự)
        name_display = name[:75] + ("..." if len(name) > 75 else "")
        sku_val = p.get("sku", "").strip()
        sku = f"\n   🏷️ <i>Phân loại: {sku_val}</i>" if sku_val else ""
        price = p.get("price")

        pid = _hash_id(f"{name} || {sku_val}")
        target_p = get_target_price(pid)
        target_info = ""
        if target_p:
            if price and price <= target_p:
                target_info = f"\n   🎯 <i>Mục tiêu: ≤ {target_p:,.0f}₫ (ĐÃ ĐẠT! 🎉)</i>"
            else:
                target_info = f"\n   🎯 <i>Mục tiêu: ≤ {target_p:,.0f}₫ (Đang chờ)</i>"

        if p.get("has_discount") and p.get("base_price"):
            base_p = p["base_price"]
            diff = p.get("discount_amount", 0)
            item_block = (
                f"<b>{i}. {name_display}</b>{sku}{target_info}\n"
                f"   💰 Giá cuối: <b>{price:,.0f}₫</b> <s>{base_p:,.0f}₫</s> <i>(-{diff:,.0f}₫)</i>"
            )
        else:
            price_str = f"{price:,.0f}₫" if price else "N/A"
            item_block = (
                f"<b>{i}. {name_display}</b>{sku}{target_info}\n"
                f"   💰 Giá cuối: <b>{price_str}</b>"
            )

        block_len = len(item_block) + 2
        # Nếu cộng thêm mặt hàng này vượt quá 3500 ký tự thì ngắt sang tin nhắn mới
        if current_char_count + block_len > 3500 and current_lines:
            messages.append("\n\n".join(current_lines))
            current_lines = [f"📦 <b>Chi tiết sản phẩm giỏ hàng (tiếp theo):</b>"]
            current_char_count = len(current_lines[0])

        current_lines.append(item_block)
        current_char_count += block_len

    # Mặt hàng hết hàng / không khả dụng
    if invalid_items:
        inv_header = "\n⚠️ <b>Mặt hàng hết hàng (không thể chọn):</b>"
        if current_char_count + len(inv_header) > 3500:
            messages.append("\n\n".join(current_lines))
            current_lines = []
            current_char_count = 0

        current_lines.append(inv_header)
        for p in invalid_items:
            name = p.get("name", "")[:60]
            sku_val = p.get("sku", "").strip()
            sku = f" <i>[{sku_val}]</i>" if sku_val else ""
            inv_block = f"• <s>{name}</s>{sku}"
            if current_char_count + len(inv_block) > 3500:
                messages.append("\n\n".join(current_lines))
                current_lines = []
                current_char_count = 0
            current_lines.append(inv_block)
            current_char_count += len(inv_block) + 2

    footer = "🛡️ <i>Chỉ kiểm tra và tính giá tại giỏ hàng, hoàn toàn không chuyển sang trang thanh toán.</i>"
    if current_char_count + len(footer) > 3700:
        messages.append("\n\n".join(current_lines))
        current_lines = [footer]
    else:
        current_lines.append(f"\n{footer}")

    if current_lines:
        messages.append("\n\n".join(current_lines))

    return messages


def format_cart_message(products: List[dict], summary: dict) -> str:
    """Format tin nhắn hiển thị danh sách sản phẩm (tương thích ngược)"""
    msgs = format_cart_messages(products, summary)
    return "\n\n".join(msgs)


def format_changes_alert(changes: list, total_change: Optional[dict] = None) -> str:
    """Format tin nhắn cảnh báo gửi tự động khi có biến động giá"""
    if not changes and not total_change:
        return ""

    lines = ["🔔 <b>CẢNH BÁO BIẾN ĐỘNG GIÁ GIỎ HÀNG!</b>\n"]

    if total_change:
        direction = total_change["direction"]
        icon = "📉" if direction == "GIẢM" else "📈"
        diff_str = f"{abs(total_change['diff']):,.0f}₫"
        lines.append(
            f"{icon} <b>TỔNG TIỀN GIỎ HÀNG ĐÃ {direction}:</b>\n"
            f"   {total_change['old_total']} ➔ <b>{total_change['new_total']}</b> ({direction} {diff_str})\n"
        )

    for c in changes:
        c_type = c.get("type", "PRICE_CHANGE")
        name = c["name"][:70]
        sku_val = c.get("sku", "").strip()
        sku_str = f"   🏷️ <i>Phân loại: <b>{sku_val}</b></i>\n" if sku_val else ""
        raw_url = c.get("url", "").strip()
        if raw_url and raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        link_str = f"   🛒 <b>Link mua ngay:</b> <a href=\"{raw_url}\">Mở sản phẩm trên Lazada</a>\n" if raw_url else ""

        if c_type == "PRICE_CHANGE":
            icon = "📉" if c["direction"] == "GIẢM" else "📈"
            old_p = f"{c['old_price']:,.0f}₫"
            new_p = f"{c['new_price']:,.0f}₫"
            diff_str = f"{abs(c['diff']):,.0f}₫"
            target_badge = ""
            if c.get("reached_target") and c.get("target_price"):
                target_badge = f"   🎯 <b>ĐÃ ĐẠT GIÁ MỤC TIÊU: ≤ {c['target_price']:,.0f}₫!</b> 🎉\n"

            lines.append(
                f"{icon} <b>{name}</b>\n"
                f"{sku_str}"
                f"{target_badge}"
                f"   💰 {old_p} ➔ <b>{new_p}</b>\n"
                f"   ⚡ Biến động: <b>{c['direction']} {diff_str}</b> ({c['diff_pct']}%)\n"
                f"{link_str}"
            )
        elif c_type == "STOCK_CHANGE":
            status = c["status"]
            icon = "🎉" if status == "CÓ HÀNG LẠI" else "⚠️"
            price_val = c.get("price")
            price_info = f"   💰 Giá hiện tại: <b>{price_val:,.0f}₫</b>\n" if price_val else ""
            lines.append(
                f"{icon} <b>{name}</b>\n"
                f"{sku_str}"
                f"   📦 Trạng thái tồn kho: <b>{status}</b>!\n"
                f"{price_info}"
                f"{link_str}"
            )

    lines.append("👉 Gõ /cart để xem toàn bộ giỏ hàng ngay!")
    return "\n".join(lines)


def get_price_summary() -> str:
    history = load_price_history()
    if not history["products"]:
        return "ℹ️ Chưa có dữ liệu sản phẩm giỏ hàng. Hãy gửi /cart hoặc /track để kiểm tra."

    lines = ["🛒 <b>DANH SÁCH GIÁ ĐANG THEO DÕI:</b>\n"]

    summary = history.get("order_summary")
    if summary and "Total" in summary:
        lines.append(f"🔥 <b>GIÁ CUỐI CÙNG HIỆN TẠI:</b> <code>{summary['Total']}</code>\n")

    for pid, data in history["products"].items():
        name = data["name"][:50]
        price = data.get("current_price")
        price_str = f"{price:,.0f}₫" if price else "N/A"
        sku = data.get("sku", "")
        sku_str = f" [{sku}]" if sku else ""

        hist = data.get("price_history", [])
        initial_price = hist[0]["price"] if hist else None
        trend = ""
        if initial_price and price and initial_price != price:
            diff = price - initial_price
            if diff < 0:
                trend = f" 📉 (-{abs(diff):,.0f}₫)"
            else:
                trend = f" 📈 (+{diff:,.0f}₫)"

        lines.append(f"• <b>{name}</b>{sku_str}\n  💰 Giá: <code>{price_str}</code>{trend}")

    last_check = history.get("last_check")
    if last_check:
        try:
            dt = datetime.fromisoformat(last_check)
            lines.append(f"\n🕐 Cập nhật: <i>{dt.strftime('%H:%M:%S %d/%m/%Y')}</i>")
        except Exception:
            pass

    return "\n".join(lines)
