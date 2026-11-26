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

import html
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from selenium.webdriver.common.by import By

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
from database import should_notify_price_change, get_target_price
from cart_api import (
    scrape_cart_via_requests,
    parse_price,
    extract_cart_from_modules,
    clean_product_url,
)
import database

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICE_HISTORY_FILE = os.path.join(BASE_DIR, "price_history.json")
CART_URL = "https://cart.lazada.vn/cart"

# Script chèn vào trình duyệt để bắt phản hồi /cart/api/async (khi click Chọn tất cả)
_CART_ASYNC_HOOK_JS = """
(function() {
    if (window.__lazHookInstalled) return;
    window.__lazHookInstalled = true;
    window.__lazAsyncQueue = [];

    function _recordPayload(url, reqBody, respText) {
        try {
            if (!url || (url.indexOf('/cart/api/async') === -1 && url.indexOf('ultron') === -1)) return;
            var op = '';
            var selectedArg = null;
            try {
                var parsed = JSON.parse(reqBody || '{}');
                op = parsed.operator || '';
                if (op === 'listHeader_H' && parsed.data && parsed.data.listHeader_H) {
                    var cb = parsed.data.listHeader_H.fields && parsed.data.listHeader_H.fields.checkbox;
                    selectedArg = cb ? cb.selected : null;
                }
            } catch(e) {}
            window.__lazAsyncQueue.push({
                ts: Date.now(),
                url: url,
                operator: op,
                selectedArg: selectedArg,
                body: respText
            });
        } catch(e) {}
    }

    var origOpen = XMLHttpRequest.prototype.open;
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
        this._lazUrl = url || '';
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
        this._lazReqBody = body;
        this.addEventListener('load', function() {
            _recordPayload(this._lazUrl, this._lazReqBody, this.responseText || '');
        });
        return origSend.apply(this, arguments);
    };

    if (window.fetch) {
        var origFetch = window.fetch;
        window.fetch = function() {
            var arg0 = arguments[0];
            var arg1 = arguments[1] || {};
            var url = typeof arg0 === 'string' ? arg0 : (arg0 && arg0.url || '');
            var reqBody = arg1 && typeof arg1.body === 'string' ? arg1.body : '';
            return origFetch.apply(this, arguments).then(function(resp) {
                try {
                    if (url && (url.indexOf('/cart/api/async') !== -1 || url.indexOf('ultron') !== -1)) {
                        resp.clone().text().then(function(txt) {
                            _recordPayload(url, reqBody, txt);
                        });
                    }
                } catch(e) {}
                return resp;
            });
        };
    }
})();
"""


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


def _hash_id(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def _extract_data_bytes(driver) -> int:
    """Đo tổng dung lượng dữ liệu mạng (bytes) của lượt tải trang qua Performance Resource Timing API"""
    if not driver:
        return 0
    try:
        val = driver.execute_script("""
            var total = 0;
            try {
                var nav = window.performance.getEntriesByType('navigation');
                if (nav && nav.length > 0) {
                    total += (nav[0].transferSize || nav[0].encodedBodySize || nav[0].decodedBodySize || 0);
                }
                var res = window.performance.getEntriesByType('resource');
                if (res) {
                    for (var i = 0; i < res.length; i++) {
                        total += (res[i].transferSize || res[i].encodedBodySize || res[i].decodedBodySize || 0);
                    }
                }
            } catch(e) {}
            return Math.round(total);
        """)
        return int(val) if val else 0
    except Exception:
        return 0


def scrape_cart_selenium(headless: bool = True, keep_alive: bool = False, max_retries: int = 2) -> Dict[str, Any]:
    """
    Truy cập giỏ hàng Lazada bằng trình duyệt Selenium Chromium, tick 'Chọn tất cả' ngay tại giỏ hàng.
    Phương án dự phòng khi Cart API cần render giao diện hoặc gặp Captcha.
    Tích hợp cơ chế tự phục hồi: nếu tab bị crash (OOM / renderer crash), tự dọn dẹp và thử lại ngay.
    """
    t_start = time.perf_counter()
    if not os.path.exists(COOKIES_FILE):
        return {
            "status": "need_login",
            "message": "Chưa có cookie. Hãy nạp cookie Lazada qua file cookie.json hoặc lệnh /cookie",
            "products": [],
            "summary": {},
            "duration": 0.0,
            "data_bytes": 0
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
                    "summary": {},
                    "duration": round(time.perf_counter() - t_start, 2),
                    "data_bytes": 0
                }

        # Đăng ký hook bắt API /cart/api/async trước khi mở trang giỏ hàng (an toàn cho cả keep_alive)
        if not getattr(driver, "_laz_async_hooked", False):
            try:
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": _CART_ASYNC_HOOK_JS})
                driver._laz_async_hooked = True
            except Exception:
                pass

        # 1. Truy cập trang giỏ hàng (áp dụng safe_get chống timeout)
        safe_get(driver, CART_URL, timeout=30)

        # Chờ thông minh: đợi React render xong checkbox 'Chọn tất cả' + danh sách sản phẩm hoặc trạng thái giỏ trống/đăng nhập (tối đa 6s)
        for _ in range(60):
            cur_u = (driver.current_url or "").lower()
            if "member.lazada.vn" in cur_u or "login" in cur_u or "_____tmd_____" in cur_u or "punish" in cur_u:
                break
            ready = driver.execute_script("""
                return Boolean(
                    (document.readyState === 'complete' || document.querySelectorAll('.cart-item').length > 0) &&
                    document.querySelector('.list-header-checkbox input, .checkbox-wrap input[type="checkbox"], .cart-empty')
                );
            """)
            if ready:
                time.sleep(0.25)
                break
            time.sleep(0.1)

        cur_url = driver.current_url.lower()
        if "_____tmd_____" in cur_url or "punish" in cur_url or "captcha" in cur_url:
            data_bytes = _extract_data_bytes(driver)
            duration = round(time.perf_counter() - t_start, 2)
            if keep_alive:
                close_shared_driver()
            return {
                "status": "captcha",
                "message": "Lazada đang hiển thị xác minh chống bot (Captcha / RGV587). Vui lòng xác minh thủ công trên trình duyệt, giữ nguyên dữ liệu cũ.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes,
            }
        if "member.lazada.vn" in cur_url or "login" in cur_url:
            data_bytes = _extract_data_bytes(driver)
            duration = round(time.perf_counter() - t_start, 2)
            if keep_alive:
                close_shared_driver()
            return {
                "status": "need_login",
                "message": "Cookie đã hết hạn hoặc không hợp lệ. Vui lòng cập nhật cookie mới.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes
            }

        # Kiểm tra xem có đang ở trạng thái phiên khách (chưa đăng nhập / cookie hết hạn) không
        auth_status = driver.execute_script("""
            var bodyText = document.body ? document.body.innerText : '';
            var hasLoginBtn = /\\b(LOGIN|SIGNUP|Sign in|Sign up)\\b/i.test(bodyText);
            var hasAccount = /'s Account|Tài khoản của|Thông tin tài khoản/i.test(bodyText);
            var initData = window.__initData__;
            var hasModules = Boolean(initData && initData.module && initData.module.data && Object.keys(initData.module.data).length > 0);
            var hasDomItems = document.querySelectorAll('.cart-item').length > 0;
            return {
                hasLoginBtn: hasLoginBtn,
                hasAccount: hasAccount,
                hasModules: hasModules || hasDomItems
            };
        """)

        if auth_status and auth_status.get("hasLoginBtn") and not auth_status.get("hasAccount") and not auth_status.get("hasModules"):
            data_bytes = _extract_data_bytes(driver)
            duration = round(time.perf_counter() - t_start, 2)
            if keep_alive:
                close_shared_driver()
            return {
                "status": "need_login",
                "message": "Phiên đăng nhập Lazada đã hết hạn (chưa đăng nhập). Vui lòng cập nhật cookie mới bằng /cookie.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes
            }

        # 2. Đảm bảo tick 'Chọn tất cả' để Lazada tính lại toàn bộ giá khuyến mãi / voucher & tải đủ 100% các mặt hàng
        async_module, summary_raw_text, block_reason = _ensure_select_all_and_capture(driver)

        if block_reason == "captcha":
            data_bytes = _extract_data_bytes(driver)
            duration = round(time.perf_counter() - t_start, 2)
            if keep_alive:
                close_shared_driver()
            return {
                "status": "captcha",
                "message": "Lazada yêu cầu xác minh Captcha / chống bot (RGV587) khi thao tác Chọn tất cả. Giữ nguyên dữ liệu giá cũ trong database.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes,
            }

        if block_reason == "need_login":
            data_bytes = _extract_data_bytes(driver)
            duration = round(time.perf_counter() - t_start, 2)
            if keep_alive:
                close_shared_driver()
            return {
                "status": "need_login",
                "message": "Phiên đăng nhập Lazada đã hết hạn (FAIL_SYS_SESSION_EXPIRED). Vui lòng cập nhật cookie mới bằng /cookie.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes,
            }

        if block_reason and block_reason.startswith("select_all_failed"):
            detail = block_reason.split(":", 1)[1] if ":" in block_reason else ""
            detail_str = f" ({detail})" if detail else ""
            data_bytes = _extract_data_bytes(driver)
            duration = round(time.perf_counter() - t_start, 2)
            if keep_alive:
                close_shared_driver()
            return {
                "status": "error",
                "message": f"Không thể tick 'Chọn tất cả' để tính giá cuối cùng trên Lazada{detail_str}. Giữ nguyên dữ liệu giá cũ trong database.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes,
            }

        # 3. Đọc dữ liệu từng sản phẩm & từng phân loại và Giá Cuối Cùng ngay tại giỏ
        products, summary_data = _extract_cart_and_summary(
            driver,
            summary_raw_text=summary_raw_text,
            async_module=async_module,
        )

        data_bytes = _extract_data_bytes(driver)
        duration = round(time.perf_counter() - t_start, 2)

        if not products:
            if not auth_status.get("hasModules"):
                if keep_alive:
                    close_shared_driver()
                return {
                    "status": "need_login",
                    "message": "Không tải được giỏ hàng cá nhân. Cookie phiên đăng nhập có thể đã hết hạn.",
                    "products": [],
                    "summary": {},
                    "duration": duration,
                    "data_bytes": data_bytes
                }
            return {
                "status": "empty",
                "message": "Giỏ hàng hiện đang trống.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes
            }

        return {
            "status": "ok",
            "message": f"Đã chọn tất cả và đọc giá {len(products)} phân loại sản phẩm trong giỏ hàng.",
            "products": products,
            "summary": summary_data,
            "duration": duration,
            "data_bytes": data_bytes
        }

    except Exception as e:
        duration = round(time.perf_counter() - t_start, 2)
        data_bytes = _extract_data_bytes(driver) if driver else 0
        if keep_alive:
            close_shared_driver()

        err_str = str(e).lower()
        is_crash = any(w in err_str for w in [
            "tab crashed", "disconnected", "session deleted",
            "no such window", "target window already closed", "cannot determine loading status"
        ])
        if is_crash:
            close_shared_driver()
            if not keep_alive and driver:
                safe_quit(driver)
            if max_retries > 0:
                print(f"[!] Phát hiện Chrome crash ({e}). Tự động giải phóng tiến trình cũ và quét lại ngay...")
                time.sleep(1.5)
                return scrape_cart_selenium(headless=headless, keep_alive=keep_alive, max_retries=max_retries - 1)

        return {
            "status": "error",
            "message": f"Lỗi khi đọc giỏ hàng: {e}",
            "products": [],
            "summary": {},
            "duration": duration,
            "data_bytes": data_bytes
        }
    finally:
        if not keep_alive:
            safe_quit(driver)


def _click_header_select_all(driver) -> None:
    """Click nút checkbox 'Chọn tất cả' ở đầu giỏ hàng bằng thao tác click thật (ưu tiên Selenium click -> fallback JS)."""
    selectors = [
        ".list-header-checkbox",
        ".list-header .next-checkbox",
        ".checkbox-wrap label",
        ".list-header-checkbox input",
        ".checkbox-wrap input[type='checkbox']",
    ]
    for sel in selectors:
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elems:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", el)
                    el.click()
                    return
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", el)
                        return
                    except Exception:
                        continue
        except Exception:
            continue

    # Dự phòng cuối bằng JS selector trực tiếp
    driver.execute_script("""
        var el = document.querySelector('.list-header-checkbox')
              || document.querySelector('.list-header .next-checkbox')
              || document.querySelector('.checkbox-wrap label')
              || document.querySelector('.list-header-checkbox input')
              || document.querySelector('.checkbox-wrap input[type="checkbox"]');
        if (el) el.click();
    """)


def _get_header_checkbox_state(driver) -> Dict[str, Any]:
    return driver.execute_script("""
        var inp = document.querySelector('.list-header-checkbox input')
               || document.querySelector('.list-header input[type="checkbox"]')
               || document.querySelector('.checkbox-wrap input[type="checkbox"]');
        var lbl = document.querySelector('.checkbox-wrap')
               || document.querySelector('.list-header-container')
               || document.querySelector('.list-header-checkbox');
        var sum = document.querySelector('.checkout-summary, .summary-section');
        var emptyEl = document.querySelector('.cart-empty');
        return {
            found: Boolean(inp),
            checked: inp ? Boolean(inp.checked || inp.getAttribute('aria-checked') === 'true') : false,
            disabled: inp ? Boolean(inp.disabled) : true,
            isEmpty: Boolean(emptyEl),
            headerText: lbl ? (lbl.innerText || '') : '',
            domCount: document.querySelectorAll('.cart-item').length,
            summaryText: sum ? (sum.innerText || '') : ''
        };
    """) or {}


def _pop_selected_async_module(driver) -> Optional[Dict[str, Any]]:
    """Lấy JSON module từ /cart/api/async trả về ngay sau thao tác Chọn tất cả."""
    raw_body = driver.execute_script("""
        var q = window.__lazAsyncQueue || [];
        for (var i = q.length - 1; i >= 0; i--) {
            if (q[i].operator === 'listHeader_H' && q[i].selectedArg === true && q[i].body) {
                return q[i].body;
            }
        }
        return null;
    """)
    if not raw_body:
        return None
    try:
        parsed = json.loads(raw_body)
        module = parsed.get("module")
        if isinstance(module, dict) and module.get("data"):
            return module
    except Exception:
        pass
    return None


def _is_summary_populated(summary_txt: str) -> bool:
    if not summary_txt:
        return False
    low = summary_txt.lower()
    if "0 sản phẩm" in low or "0 items" in low or "thanh toán(0)" in low or "checkout(0)" in low:
        return False
    return True


def _detect_block_in_async_or_dom(driver) -> Optional[str]:
    """Phát hiện Captcha / RGV587 hoặc hết hạn phiên đăng nhập trong /cart/api/async hoặc DOM."""
    try:
        status = driver.execute_script("""
            var q = window.__lazAsyncQueue || [];
            for (var i = q.length - 1; i >= 0; i--) {
                var b = (q[i].body || '').toLowerCase();
                if (b.indexOf('fail_sys_session_expired') !== -1 || b.indexOf('session过期') !== -1) {
                    return 'need_login';
                }
                if (
                    b.indexOf('rgv587') !== -1 ||
                    b.indexOf('fail_sys_user_validate') !== -1 ||
                    b.indexOf('_____tmd_____') !== -1 ||
                    b.indexOf('action=captcha') !== -1 ||
                    b.indexOf('punish') !== -1
                ) {
                    return 'captcha';
                }
            }
            if (document.querySelector('#baxia-punish, .baxia-dialog, .nc-container, .nc_wrapper, #nc_1_wrapper, iframe[src*="punish"], iframe[src*="captcha"], iframe[src*="tmd"]')) {
                return 'captcha';
            }
            return null;
        """)
        return status
    except Exception:
        return None


def _get_async_diagnostic(driver) -> str:
    """Trích xuất ngắn gọn nguyên nhân từ hàng đợi /cart/api/async nếu tick không thành công."""
    try:
        diag = driver.execute_script("""
            var q = window.__lazAsyncQueue || [];
            if (!q.length) return 'no_async_xhr';
            var last = q[q.length - 1];
            var body = last.body || '';
            try {
                var j = JSON.parse(body);
                if (j.ret) return 'api_ret=' + JSON.stringify(j.ret);
                if (j.success === false) return 'api_success=false';
            } catch(e) {}
            return 'queue_len=' + q.length + ',op=' + (last.operator || '');
        """)
        return str(diag or "")
    except Exception:
        return ""


def _ensure_select_all_and_capture(driver) -> tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """
    Đảm bảo tất cả mặt hàng hợp lệ trong giỏ hàng đều được tick chọn:
    - Nếu 'Chọn tất cả' ĐÃ được chọn sẵn từ phiên trước và summary có tiền: giữ nguyên (cuộn tải thêm trang nếu thiếu) để tránh double-toggle gây rate-limit.
    - Nếu chưa chọn: click chọn thật và đợi /cart/api/async tính mới 100% giá thực tế.
    - Phát hiện ngay Captcha / RGV587, hết hạn cookie, hoặc lỗi không tick được để tránh ghi đè dữ liệu sai.
    - Trả về (async_module, summary_raw_text, block_reason).
    """
    try:
        driver.execute_script(_CART_ASYNC_HOOK_JS)
        issue = _detect_block_in_async_or_dom(driver)
        if issue:
            return None, "", issue

        state = _get_header_checkbox_state(driver)
        if state.get("isEmpty") or not state.get("found"):
            return None, state.get("summaryText", ""), None

        if state.get("disabled"):
            # Toàn bộ sản phẩm đều hết hàng / vô hiệu -> đọc trực tiếp trạng thái hiện tại
            return None, state.get("summaryText", ""), None

        # Nếu 'Chọn tất cả' ĐÃ được chọn sẵn từ trước và summary đã có số tiền -> không toggle tắt/bật gây spam request
        if state.get("checked") and _is_summary_populated(state.get("summaryText", "")):
            m_hdr = re.search(r'\((\d+)', state.get("headerText", ""))
            expected_cnt = int(m_hdr.group(1)) if m_hdr else 0
            if expected_cnt > state.get("domCount", 0):
                # Cuộn xuống cuối để kích hoạt lazy-load trang 2 nếu có
                try:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight || 4000);")
                    time.sleep(0.8)
                    driver.execute_script("window.scrollTo(0, 0);")
                except Exception:
                    pass
                state = _get_header_checkbox_state(driver)
            return None, state.get("summaryText", ""), None

        # Thực hiện chọn tất cả (tối đa 2 lần click phòng trường hợp checkbox đang ở trạng thái mixed)
        async_module: Optional[Dict[str, Any]] = None
        for _attempt in range(2):
            cur = _get_header_checkbox_state(driver)
            if cur.get("checked") and _is_summary_populated(cur.get("summaryText", "")):
                break

            driver.execute_script("window.__lazAsyncQueue = [];")
            _click_header_select_all(driver)

            for _ in range(60):
                issue = _detect_block_in_async_or_dom(driver)
                if issue:
                    return None, "", issue

                async_module = _pop_selected_async_module(driver)
                if async_module is not None:
                    # Cho React 150ms render lại DOM đồng bộ với response vừa nhận
                    time.sleep(0.15)
                    break

                # Kiểm tra nếu có phản hồi bỏ chọn (trạng thái mixed vừa chuyển về unchecked) -> thoát để click lại
                unselected_fired = driver.execute_script("""
                    var q = window.__lazAsyncQueue || [];
                    for (var i = q.length - 1; i >= 0; i--) {
                        if (q[i].operator === 'listHeader_H' && q[i].selectedArg === false) return true;
                    }
                    return false;
                """)
                if unselected_fired:
                    break

                cur_now = _get_header_checkbox_state(driver)
                if cur_now.get("checked") and _is_summary_populated(cur_now.get("summaryText", "")):
                    q_len = driver.execute_script("return (window.__lazAsyncQueue || []).length;") or 0
                    if q_len > 0:
                        time.sleep(0.15)
                        break

                time.sleep(0.1)

            if async_module is not None:
                break

        issue = _detect_block_in_async_or_dom(driver)
        if issue:
            return None, "", issue

        final_state = _get_header_checkbox_state(driver)
        summary_txt = final_state.get("summaryText", "")
        if async_module is None and not (final_state.get("checked") and _is_summary_populated(summary_txt)):
            diag = _get_async_diagnostic(driver)
            return None, summary_txt, f"select_all_failed:{diag}" if diag else "select_all_failed"

        return async_module, summary_txt, None
    except Exception as e:
        print(f"[!] Lỗi khi tick Chọn tất cả: {e}")
        return None, "", f"select_all_failed:{e}"


def _parse_summary_text(summary_raw_text: str) -> Dict[str, Any]:
    """Phân tích phần tóm tắt đơn hàng từ text DOM (hỗ trợ cả tiếng Việt và tiếng Anh)."""
    summary_data: Dict[str, Any] = {}
    if not summary_raw_text:
        return summary_data

    m_total = re.search(r'(?:Tổng cộng|Total)[\s\t]*((?:₫?\s*[\d.,]+(?:\s*₫)?))', summary_raw_text, re.IGNORECASE)
    if m_total:
        val = m_total.group(1).strip()
        parsed_val = parse_price(val)
        if parsed_val and parsed_val > 0:
            summary_data['Total'] = val

    m_sub = re.search(r'(?:Tạm tính|Subtotal)[^\n]*\n\s*((?:₫?\s*[\d.,]+(?:\s*₫)?))', summary_raw_text, re.IGNORECASE)
    if m_sub:
        summary_data['Subtotal'] = m_sub.group(1).strip()

    m_promo = re.search(r'(?:Khuyến mãi|Promotion)[^\n]*\n\s*(-?\s*₫?\s*[\d.,]+(?:\s*₫)?)', summary_raw_text, re.IGNORECASE)
    if m_promo:
        summary_data['Promotion'] = m_promo.group(1).strip()

    m_ship = re.search(r'(?:Phí vận chuyển|Shipping Fee)[^\n]*\n\s*([^\n]+)', summary_raw_text, re.IGNORECASE)
    if m_ship:
        summary_data['Shipping Fee'] = m_ship.group(1).strip()

    return summary_data


def _extract_dom_cart_items(driver) -> List[Dict[str, Any]]:
    """Đọc danh sách sản phẩm và giá đang hiển thị trực tiếp từ các phần tử DOM .cart-item."""
    raw_items = driver.execute_script("""
        var out = [];
        document.querySelectorAll('.cart-item').forEach(function(el) {
            var titleEl = el.querySelector('a.title, .title, [class*="item-title"]');
            if (!titleEl) return;
            var title = (titleEl.innerText || '').trim();
            if (!title) return;

            var skuEl = el.querySelector('a.sku, .sku, [class*="item-sku"]');
            var curEl = el.querySelector('.current-price');
            var discEl = el.querySelector('.discount-price-tip-price');
            var qtyEl = el.querySelector('.automation-item-quantity input, .next-number-picker-input input, input[type="tel"]');
            var cbInput = el.querySelector('input[type="checkbox"]');
            var isInvalid = Boolean(
                el.closest('.invalid-list, .cart-invalid-list, .automation-invalid-group-item, [class*="invalid"]') ||
                (cbInput && cbInput.disabled)
            );

            out.push({
                title: title,
                sku: skuEl ? (skuEl.innerText || '').trim() : '',
                href: titleEl.getAttribute('href') || '',
                current_price: curEl ? (curEl.innerText || '').trim() : '',
                discount_price: discEl ? (discEl.innerText || '').trim() : '',
                quantity: qtyEl ? qtyEl.value : '1',
                checked: cbInput ? Boolean(cbInput.checked) : false,
                valid: !isInvalid
            });
        });
        return out;
    """) or []

    products: List[Dict[str, Any]] = []
    for item in raw_items:
        title = item.get("title", "").strip()
        if not title:
            continue
        sku_text = re.sub(r'\s+', ' ', (item.get("sku") or "").strip())
        url = clean_product_url(item.get("href") or "")

        base_price = parse_price(item.get("current_price"))
        discount_price = parse_price(item.get("discount_price")) if item.get("discount_price") else None
        real_price = discount_price if (discount_price is not None and discount_price > 0) else base_price
        has_disc = bool(discount_price and base_price and discount_price < base_price)
        disc_amt = (base_price - discount_price) if has_disc else 0
        try:
            qty = max(1, int(str(item.get("quantity") or "1").strip()))
        except ValueError:
            qty = 1

        products.append({
            "name": title,
            "sku": sku_text,
            "valid": bool(item.get("valid", True)),
            "selected": bool(item.get("checked", False)),
            "quantity": qty,
            "base_price": base_price,
            "discount_price": discount_price,
            "price": real_price,
            "has_discount": has_disc,
            "discount_amount": disc_amt,
            "url": url,
            "timestamp": datetime.now().isoformat(),
        })
    return products


def _extract_cart_and_summary(
    driver,
    summary_raw_text: Optional[str] = None,
    async_module: Optional[Dict[str, Any]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    summary_data: Dict[str, Any] = {}

    # 1. Ưu tiên đọc dữ liệu chính xác từ phản hồi /cart/api/async sau khi tick 'Chọn tất cả'
    if async_module and isinstance(async_module, dict):
        mod_data = async_module.get("data", {})
        hierarchy = async_module.get("hierarchy")
        if mod_data:
            products, summary_data = extract_cart_from_modules(mod_data, hierarchy=hierarchy)

    # 2. Kiểm tra hoặc dự phòng từ DOM hiện tại sau khi đã tick 'Chọn tất cả'
    dom_products = _extract_dom_cart_items(driver)
    if not products or len(dom_products) > len(products):
        products = dom_products

    # 3. Dự phòng cuối nếu cả async và DOM đều không đọc được -> đọc window.__initData__ kèm hierarchy
    if not products:
        try:
            init_data = driver.execute_script("return window.__initData__;")
            if init_data and isinstance(init_data, dict):
                module_obj = init_data.get("module", {})
                mod_data = module_obj.get("data", {})
                hierarchy = module_obj.get("hierarchy")
                if mod_data:
                    products, init_summary = extract_cart_from_modules(mod_data, hierarchy=hierarchy)
                    for k, v in init_summary.items():
                        summary_data.setdefault(k, v)
        except Exception as e:
            print(f"[!] Lỗi trích xuất __initData__: {e}")

    # 4. Bổ sung / đối chiếu phần tóm tắt đơn hàng từ DOM .checkout-summary
    try:
        if not summary_raw_text:
            summary_raw_text = driver.execute_script("""
                var el = document.querySelector('.checkout-summary, .summary-section');
                return el ? el.innerText : '';
            """)
        dom_summary = _parse_summary_text(summary_raw_text or "")
        for k, v in dom_summary.items():
            if v and (k not in summary_data or not summary_data[k]):
                summary_data[k] = v
    except Exception as e:
        print(f"[!] Lỗi đọc summary text: {e}")

    return products, summary_data


def scrape_cart(headless: bool = True, keep_alive: bool = False, prefer_api: bool = False) -> Dict[str, Any]:
    """
    Truy cập giỏ hàng Lazada và trích xuất danh sách sản phẩm & Giá Cuối Cùng:
    - Mặc định (prefer_api=False): Chạy qua Chromium headless, click 'Chọn tất cả' trong giỏ để kích hoạt toàn bộ Voucher sàn, Voucher shop, LazCoins và lấy chính xác 100% Giá Cuối Cùng.
    - Chế độ API siêu nhẹ (prefer_api=True): Dùng Cart API qua requests trực tiếp (< 0.5s, 5-20 KB) khi chỉ cần đọc danh sách sản phẩm cơ bản.
    """
    if prefer_api:
        api_res = scrape_cart_via_requests()
        status = api_res.get("status")
        # Nếu API thành công hoặc phát hiện cookie hết hạn / giỏ trống -> trả về ngay
        if status in ("ok", "need_login", "empty"):
            return api_res

    # Chạy Selenium Chromium để click Chọn tất cả và tính Giá Cuối Cùng chính xác
    return scrape_cart_selenium(headless=headless, keep_alive=keep_alive)


def sync_cart_snapshot(
    products: List[Dict[str, Any]],
    summary: Dict[str, Any],
    collect_changes: bool = False,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Cập nhật giá mới nhất của TẤT CẢ sản phẩm vào cả price_history.json và SQLite database
    (bất kể giá mới cao hơn hay thấp hơn giá đáy).
    Nếu collect_changes=True, trả về danh sách biến động từng mặt hàng đủ điều kiện báo động.
    """
    history = load_price_history()
    now = datetime.now().isoformat()
    changes: List[Dict[str, Any]] = []

    for p in products:
        name = p["name"]
        sku = p.get("sku", "")
        curr_price = p["price"]
        curr_valid = p.get("valid", True)
        clean_url = clean_product_url(p.get("url", ""))
        if clean_url:
            p["url"] = clean_url
        # Khóa định danh duy nhất cho từng phân loại của từng sản phẩm
        pid = _hash_id(f"{name} || {sku}")

        if pid in history["products"]:
            prod_entry = history["products"][pid]
            old_price = prod_entry.get("current_price")
            old_valid = prod_entry.get("valid", True)

            # 1. Luôn cập nhật giá mới vào bộ nhớ lịch sử dù cao hơn hay thấp hơn giá đáy
            if old_price is None and curr_price is not None:
                prod_entry["current_price"] = curr_price
                if not prod_entry.get("price_history"):
                    prod_entry["price_history"] = [{"price": curr_price, "timestamp": now}]
            elif old_price is not None and curr_price is not None and old_price != curr_price:
                if collect_changes:
                    diff = curr_price - old_price
                    pct = (diff / old_price) * 100 if old_price > 0 else 0.0
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
                            "url": clean_url,
                            "target_price": target_price,
                            "reached_target": bool(target_price and curr_price <= target_price),
                        })
                prod_entry.setdefault("price_history", []).append({"price": curr_price, "timestamp": now})
                prod_entry["current_price"] = curr_price
            elif curr_price is not None:
                prod_entry["current_price"] = curr_price

            # 2. Phát hiện thay đổi trạng thái tồn kho (Hết hàng / Có hàng lại)
            if old_valid != curr_valid:
                if collect_changes:
                    changes.append({
                        "type": "STOCK_CHANGE",
                        "name": name,
                        "sku": sku,
                        "status": "CÓ HÀNG LẠI" if curr_valid else "HẾT HÀNG",
                        "price": curr_price,
                        "url": clean_url,
                    })
                prod_entry["valid"] = curr_valid

            prod_entry["last_check"] = now
            prod_entry["sku"] = sku
            if p.get("base_price") is not None:
                prod_entry["base_price"] = p.get("base_price")
            if clean_url:
                prod_entry["url"] = clean_url
        else:
            # Sản phẩm / phân loại mới được thêm vào giỏ
            history["products"][pid] = {
                "name": name,
                "sku": sku,
                "valid": curr_valid,
                "current_price": curr_price,
                "base_price": p.get("base_price"),
                "url": clean_url,
                "first_seen": now,
                "last_check": now,
                "price_history": [{"price": curr_price, "timestamp": now}] if curr_price is not None else [],
            }

    history["last_check"] = now
    history["order_summary"] = summary
    save_price_history(history)

    # Luôn lưu đồng bộ toàn bộ sản phẩm & giá mới vào SQLite database và gán STT chuẩn xác
    try:
        products = database.save_cart_to_db(products, summary)
    except Exception as e:
        print(f"[!] Lỗi lưu giỏ hàng SQLite: {e}")

    return products, changes


def track_prices(headless: bool = True, keep_driver: bool = False, prefer_api: bool = False) -> dict:
    """
    Theo dõi biến động giá thực tế của TẤT CẢ sản phẩm và TẤT CẢ phân loại (SKU).
    Không phát cảnh báo biến động tổng giá trị giỏ hàng.
    """
    scrape_res = scrape_cart(headless=headless, keep_alive=keep_driver, prefer_api=prefer_api)
    if scrape_res["status"] != "ok":
        return scrape_res

    products = scrape_res["products"]
    summary = scrape_res["summary"]
    products, changes = sync_cart_snapshot(products, summary, collect_changes=True)

    return {
        "status": "ok",
        "total_products": len(products),
        "products": products,
        "summary": summary,
        "changes": changes,
        "total_change": None,
        "timestamp": datetime.now().isoformat(),
        "duration": scrape_res.get("duration", 0.0),
        "data_bytes": scrape_res.get("data_bytes", 0),
    }


def format_cart_messages(products: List[dict], summary: dict) -> List[str]:
    """
    Định dạng danh sách sản phẩm (kèm link sản phẩm) và tổng tiền giỏ hàng gọn gàng.
    Tự động chia nhỏ tin nhắn nếu vượt giới hạn 4096 ký tự của Telegram.
    """
    messages = []
    current_lines = []

    valid_items = [p for p in products if p.get("valid", True)]
    invalid_items = [p for p in products if not p.get("valid", True)]
    total_count = len(products)

    # 1. Header & Tóm tắt giỏ hàng
    current_lines.append(f"🛒 <b>GIỎ HÀNG LAZADA ({total_count} mặt hàng)</b>")

    if summary and "Total" in summary:
        current_lines.append(f"💵 <b>Giá cuối:</b> <code>{html.escape(str(summary['Total']))}</code>")
        sub = summary.get("Subtotal")
        promo = summary.get("Promotion")
        ship = summary.get("Shipping Fee")
        details = []
        if sub: details.append(f"Tạm tính: {html.escape(str(sub))}")
        if promo: details.append(f"Giảm: {html.escape(str(promo))}")
        if ship: details.append(f"Ship: {html.escape(str(ship))}")
        if details:
            current_lines.append(f"<i>({', '.join(details)})</i>")
        current_lines.append("────────────────────\n")

    current_lines.append("📦 <b>Danh sách sản phẩm:</b>")
    current_char_count = sum(len(line) + 2 for line in current_lines)

    for i, p in enumerate(valid_items, 1):
        stt = p.get("stt", i)
        name = p.get("name", "").strip()
        name_short = name[:70] + ("..." if len(name) > 70 else "")
        name_display = html.escape(name_short, quote=False)
        sku_raw = p.get("sku", "").strip()
        sku = f"\n   🏷️ <i>Phân loại: {html.escape(sku_raw, quote=False)}</i>" if sku_raw else ""
        price = p.get("price")

        clean_url = clean_product_url(p.get("url", ""))
        link_line = f"\n   🔗 <a href=\"{html.escape(clean_url, quote=True)}\">Link sản phẩm</a>" if clean_url else ""

        pid = _hash_id(f"{name} || {sku_raw}")
        target_p = get_target_price(pid)
        target_info = ""
        if target_p:
            if price is not None and price <= target_p:
                target_info = f"\n   🎯 <i>Giá đáy: ≤ {target_p:,.0f}₫ (Đã đạt 🎉)</i>"
            else:
                target_info = f"\n   🎯 <i>Giá đáy: ≤ {target_p:,.0f}₫</i>"

        if p.get("has_discount") and p.get("base_price"):
            base_p = p["base_price"]
            diff = p.get("discount_amount", 0)
            item_block = (
                f"<b>{stt}. {name_display}</b>{sku}{target_info}\n"
                f"   💰 Giá: <b>{price:,.0f}₫</b> <s>{base_p:,.0f}₫</s> <i>(-{diff:,.0f}₫)</i>"
                f"{link_line}"
            )
        else:
            price_str = f"{price:,.0f}₫" if price else "N/A"
            item_block = (
                f"<b>{stt}. {name_display}</b>{sku}{target_info}\n"
                f"   💰 Giá: <b>{price_str}</b>"
                f"{link_line}"
            )

        block_len = len(item_block) + 2
        if current_char_count + block_len > 3500 and current_lines:
            messages.append("\n\n".join(current_lines))
            current_lines = ["📦 <b>Danh sách sản phẩm (tiếp theo):</b>"]
            current_char_count = len(current_lines[0])

        current_lines.append(item_block)
        current_char_count += block_len

    # Mặt hàng hết hàng
    if invalid_items:
        inv_header = "\n⚠️ <b>Mặt hàng hết hàng:</b>"
        if current_char_count + len(inv_header) > 3500:
            messages.append("\n\n".join(current_lines))
            current_lines = []
            current_char_count = 0

        current_lines.append(inv_header)
        for p in invalid_items:
            name_safe = html.escape(p.get("name", "")[:60], quote=False)
            sku_raw = p.get("sku", "").strip()
            sku = f" <i>[{html.escape(sku_raw, quote=False)}]</i>" if sku_raw else ""
            clean_url = clean_product_url(p.get("url", ""))
            inv_link = f" — <a href=\"{html.escape(clean_url, quote=True)}\">Link</a>" if clean_url else ""
            inv_block = f"• <s>{name_safe}</s>{sku}{inv_link}"
            if current_char_count + len(inv_block) > 3500:
                messages.append("\n\n".join(current_lines))
                current_lines = []
                current_char_count = 0
            current_lines.append(inv_block)
            current_char_count += len(inv_block) + 2

    footer = "💡 <i>Mẹo: Nhắn nhanh <b>&lt;STT&gt; &lt;giá&gt;</b> (VD: <code>1 100k</code>, <code>2 50k</code>) để đặt giá đáy tức thì!</i>"
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
    """Format tin nhắn cảnh báo gửi tự động khi có biến động giá từng sản phẩm (không báo tổng giỏ)"""
    if not changes:
        return ""

    lines = ["🔔 <b>BIẾN ĐỘNG GIÁ SẢN PHẨM</b>\n"]

    for c in changes:
        c_type = c.get("type", "PRICE_CHANGE")
        name = html.escape(c["name"][:70], quote=False)
        sku_val = c.get("sku", "").strip()
        sku_str = f"   🏷️ <i>Phân loại: <b>{html.escape(sku_val, quote=False)}</b></i>\n" if sku_val else ""
        clean_url = clean_product_url(c.get("url", ""))
        link_str = f"   🛒 <a href=\"{html.escape(clean_url, quote=True)}\">Mua ngay trên Lazada</a>\n" if clean_url else ""

        if c_type == "PRICE_CHANGE":
            icon = "📉" if c["direction"] == "GIẢM" else "📈"
            old_p = f"{c['old_price']:,.0f}₫"
            new_p = f"{c['new_price']:,.0f}₫"
            diff_str = f"{abs(c['diff']):,.0f}₫"
            target_badge = ""
            if c.get("reached_target") and c.get("target_price"):
                target_badge = f"   🎯 <b>ĐẠT GIÁ ĐÁY: ≤ {c['target_price']:,.0f}₫</b>\n"

            lines.append(
                f"{icon} <b>{name}</b>\n"
                f"{sku_str}"
                f"{target_badge}"
                f"   💰 {old_p} ➔ <b>{new_p}</b> ({c['direction']} {diff_str}, {c['diff_pct']}%)\n"
                f"{link_str}"
            )
        elif c_type == "STOCK_CHANGE":
            status = c["status"]
            icon = "🎉" if status == "CÓ HÀNG LẠI" else "⚠️"
            price_val = c.get("price")
            price_info = f"   💰 Giá: <b>{price_val:,.0f}₫</b>\n" if price_val else ""
            lines.append(
                f"{icon} <b>{name}</b>\n"
                f"{sku_str}"
                f"   📦 Tồn kho: <b>{html.escape(status, quote=False)}</b>\n"
                f"{price_info}"
                f"{link_str}"
            )

    lines.append("👉 Gõ /cart để xem giỏ hàng.")
    return "\n".join(lines)


def get_price_summary() -> str:
    """
    Lấy danh sách giá hiện tại và xu hướng biến động:
    - Luôn hiển thị đầy đủ giá hiện tại thực tế được lưu trong CSDL SQLite
    - Hiển thị mức giá đáy (nếu có) để người dùng theo dõi khoảng cách giá
    """
    # 1. Ưu tiên đọc trực tiếp từ SQLite Database (chuẩn hóa STT & giá tức thì)
    try:
        cart_items = database.get_cart_items_db()
        if cart_items:
            lines = ["🛒 <b>DANH SÁCH GIÁ ĐANG THEO DÕI:</b>\n"]
            summary = database.get_cart_summary_db()
            if summary and "Total" in summary and summary["Total"]:
                lines.append(f"🔥 <b>GIÁ CUỐI CÙNG HIỆN TẠI:</b> <code>{summary['Total']}</code>\n")

            conn = database.get_connection()
            for p in cart_items:
                stt = p["stt"]
                name = p["name"][:45]
                price = p.get("price") or 0
                price_str = f"{price:,.0f}₫" if price else "N/A"
                sku = p.get("sku", "")
                sku_str = f" [{sku[:20]}]" if sku else ""
                pid = p["pid"]

                # Lấy giá khởi điểm từ price_history để tính xu hướng
                hist_rows = conn.execute("SELECT price FROM price_history WHERE pid = ? ORDER BY id ASC", (pid,)).fetchall()
                trend = ""
                if hist_rows and len(hist_rows) > 1:
                    initial_price = float(hist_rows[0]["price"])
                    if initial_price != price:
                        diff = price - initial_price
                        trend = f" 📉 (-{abs(diff):,.0f}₫)" if diff < 0 else f" 📈 (+{diff:,.0f}₫)"

                # Kiểm tra giá đáy
                target_p = database.get_target_price_db(pid)
                target_str = f" | 🎯 Đáy: <code>≤ {target_p:,.0f}₫</code>" if target_p else ""

                lines.append(f"• <b>#{stt}. {name}</b>{sku_str}\n  💰 Giá hiện tại: <code>{price_str}</code>{trend}{target_str}")

            updated_at = summary.get("updated_at")
            if updated_at:
                try:
                    dt = datetime.fromisoformat(updated_at)
                    lines.append(f"\n🕐 Cập nhật CSDL: <i>{dt.strftime('%H:%M:%S %d/%m/%Y')}</i>")
                except Exception:
                    pass

            lines.append("👉 Gõ /cart để xem giỏ hàng đầy đủ chi tiết.")
            return "\n".join(lines)
    except Exception as e:
        print(f"[!] Lỗi đọc SQLite trong get_price_summary: {e}")

    # 2. Fallback nếu SQLite chưa có dữ liệu
    history = load_price_history()
    if not history.get("products"):
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
