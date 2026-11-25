"""
Lazada Cart API Fetcher (Requests-based)
Quét giỏ hàng siêu tốc (< 0.5s) và siêu nhẹ (5-20 KB) qua API trực tiếp bằng thư viện requests:
- Giữ an toàn tối đa cho Cookie: Không mở trình duyệt, không dấu vết automation (navigator.webdriver = false).
- Tự động tính chữ ký mtop (mtop.lazada.carts.ultron.query.cutover) với token _m_h5_tk.
- Tự động dự phòng qua GET https://cart.lazada.vn/cart (trích xuất window.__initData__).
- Hỗ trợ auto-retry khi token mtop hết hạn (_m_h5_tk refresh).
"""

import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import requests

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(BASE_DIR, "lazada_cookies.json")

MTOP_APP_KEY = "24677475"
MTOP_API = "mtop.lazada.carts.ultron.query.cutover"
MTOP_URL = "https://acs-m.lazada.vn/h5/mtop.lazada.carts.ultron.query.cutover/1.0/"
CART_PAGE_URL = "https://cart.lazada.vn/cart"

# Headers chuẩn giả lập Chrome 131 Desktop
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://cart.lazada.vn",
    "Referer": "https://cart.lazada.vn/",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.lazada.vn/",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-site",
    "Upgrade-Insecure-Requests": "1",
}


def parse_price(price_text: Any) -> Optional[float]:
    """Chuyển đổi giá trị hoặc chuỗi giá tiền thành số thực (hỗ trợ cả float/int, VNĐ dấu chấm và dấu phẩy)."""
    if price_text is None or isinstance(price_text, bool):
        return None
    if isinstance(price_text, (int, float)):
        return float(price_text)

    cleaned = re.sub(r'[^\d.,]', '', str(price_text))
    if not cleaned:
        return None

    # Dạng tiền Việt (VD: 1.236.000 hoặc 330.144) -> bỏ dấu chấm phần nghìn
    if cleaned.count('.') > 1 or re.search(r'\.\d{3}(?:$|[^\d])', cleaned):
        cleaned = cleaned.replace('.', '')
    # Dạng phân cách phần nghìn bằng dấu phẩy (VD: 1,236,000 hoặc 835,200)
    if cleaned.count(',') > 1 or ('.' not in cleaned and re.search(r',\d{3}$', cleaned)):
        cleaned = cleaned.replace(',', '')
    else:
        cleaned = cleaned.replace(',', '.')

    try:
        return float(cleaned)
    except ValueError:
        return None


def load_cookie_dict() -> Dict[str, str]:
    """Đọc cookies từ file lazada_cookies.json và chuyển về dạng key-value dict"""
    if not os.path.exists(COOKIES_FILE):
        return {}
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        return {c["name"]: c["value"] for c in cookies if "name" in c and "value" in c}
    except Exception as e:
        logger.warning(f"Không thể đọc file cookies: {e}")
        return {}


def update_saved_cookie(name: str, value: str) -> None:
    """Cập nhật giá trị 1 cookie trong file lazada_cookies.json nếu có thay đổi từ server"""
    if not os.path.exists(COOKIES_FILE):
        return
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        updated = False
        for c in cookies:
            if c.get("name") == name:
                c["value"] = value
                updated = True
                break
        if not updated:
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".lazada.vn",
                "path": "/"
            })
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def calculate_mtop_sign(token: str, t: str, app_key: str, data: str) -> str:
    """
    Tính mã chữ ký HMAC-MD5 cho Alibaba/Lazada Mtop Gateway:
    sign = md5(token & t & appKey & data)
    Trong đó token lấy từ cookie _m_h5_tk (phần trước dấu gạch dưới).
    """
    sign_str = f"{token}&{t}&{app_key}&{data}"
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest()


def _collect_ordered_module_keys(mod_data: Dict[str, Any], hierarchy: Optional[Dict[str, Any]] = None) -> List[str]:
    """Thu thập thứ tự key node trong giỏ hàng theo cấu trúc hierarchy.structure nếu có."""
    ordered: List[str] = []
    seen = set()

    struct = hierarchy.get("structure", {}) if isinstance(hierarchy, dict) else {}
    if isinstance(struct, dict) and struct:
        def _walk(node_key: str) -> None:
            for child in struct.get(node_key, []) or []:
                if child in seen:
                    continue
                seen.add(child)
                ordered.append(child)
                if child in struct:
                    _walk(child)

        root_key = "leftContainer_CL" if "leftContainer_CL" in struct else hierarchy.get("root", "root_0")
        if isinstance(root_key, str) and root_key in struct:
            _walk(root_key)
        # Bổ sung rightContainer / orderSummary nếu nằm ngoài leftContainer
        if "rightContainer_CR" in struct:
            _walk("rightContainer_CR")

    # Đảm bảo không bỏ sót bất kỳ key nào ngoài cây hierarchy
    for key in mod_data.keys():
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    return ordered


def _is_zero_currency_text(text: str) -> bool:
    val = parse_price(text)
    return val is None or val <= 0


def extract_cart_from_modules(
    mod_data: Dict[str, Any],
    hierarchy: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Trích xuất danh sách tất cả sản phẩm & phân loại (SKU) và tổng đơn hàng từ module data.
    Tương thích cả tiếng Việt và tiếng Anh, hỗ trợ duyệt theo hierarchy.structure chuẩn thứ tự giỏ hàng.
    """
    products: List[Dict[str, Any]] = []
    summary_data: Dict[str, Any] = {}
    calculated_total = 0.0
    ordered_keys = _collect_ordered_module_keys(mod_data, hierarchy)

    for key in ordered_keys:
        val = mod_data.get(key)
        if not isinstance(val, dict):
            continue

        tag = val.get("tag")

        # 1. Trích xuất thông tin sản phẩm và từng phân loại SKU
        if tag == "item":
            fields = val.get("fields", {})
            title = (fields.get("title") or "").strip()
            if not title:
                continue

            valid = bool(fields.get("valid", True))
            selected = bool((fields.get("checkbox") or {}).get("selected", False))
            qty_raw = (fields.get("quantity") or {}).get("quantity")
            quantity = int(qty_raw) if isinstance(qty_raw, (int, float)) and qty_raw > 0 else 1

            sku_info = fields.get("sku", {}) or fields.get("skuInfo", {})
            sku_text = re.sub(r'\s+', ' ', (sku_info.get("skuText") or "").strip())
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

            if valid and real_price:
                calculated_total += real_price * quantity

            has_disc = bool(discount_price and base_price and discount_price < base_price)
            disc_amt = (base_price - discount_price) if has_disc else 0

            products.append({
                "name": title,
                "sku": sku_text,
                "valid": valid,
                "selected": selected,
                "quantity": quantity,
                "base_price": base_price,
                "discount_price": discount_price,
                "price": real_price,
                "has_discount": has_disc,
                "discount_amount": disc_amt,
                "url": url,
                "image": fields.get("img") or "",
                "shop_name": fields.get("sellerName") or "",
                "timestamp": datetime.now().isoformat(),
            })

        # 2. Trích xuất tổng đơn hàng (Order Total)
        elif tag == "orderTotal":
            fields = val.get("fields", {})
            payment = fields.get("payment", {})
            pay_str = (payment.get("pay") or "").strip()
            if pay_str and not _is_zero_currency_text(pay_str):
                summary_data["Total"] = pay_str

        # 3. Trích xuất chi tiết tạm tính / khuyến mãi / phí vận chuyển (hỗ trợ cả tiếng Việt & tiếng Anh)
        elif tag == "orderSummary":
            fields = val.get("fields", {})
            for s in fields.get("summarys", []) or []:
                stitle = (s.get("title") or "").strip()
                sval = (s.get("value") or "").strip()
                if not stitle or not sval:
                    continue
                low = stitle.lower()
                if "tạm tính" in low or "subtotal" in low:
                    summary_data["Subtotal"] = sval
                elif "phí vận chuyển" in low or "shipping" in low:
                    summary_data["Shipping Fee"] = sval
                elif "khuyến mãi" in low or "promotion" in low or "giảm" in low or "voucher" in low:
                    summary_data["Promotion"] = sval
                else:
                    summary_data[stitle] = sval

    # Dự phòng nếu chưa có Total hợp lệ
    if ("Total" not in summary_data or _is_zero_currency_text(summary_data["Total"])) and calculated_total > 0:
        summary_data["Total"] = f"{int(round(calculated_total)):,}₫".replace(",", ".")

    return products, summary_data


# Session requests toàn cục có HTTP keep-alive để tái sử dụng kết nối (giảm latency xuống < 0.2s)
_api_session: Optional[requests.Session] = None


def get_api_session() -> requests.Session:
    """Lấy hoặc khởi tạo requests.Session có keep-alive connection pooling"""
    global _api_session
    if _api_session is None:
        _api_session = requests.Session()
    return _api_session


def fetch_cart_via_mtop(cookie_dict: Dict[str, str], timeout: float = 8.0) -> Dict[str, Any]:
    """
    Gọi trực tiếp API mtop.lazada.carts.ultron.query.cutover:
    - Payload JSON nhỏ gọn, phản hồi trong ~0.2s.
    - Tiết kiệm 95% băng thông và 100% tài nguyên CPU/RAM so với Selenium.
    """
    t_start = time.perf_counter()
    session = get_api_session()

    token_cookie = cookie_dict.get("_m_h5_tk", "")
    token = token_cookie.split("_")[0] if token_cookie else ""
    t = str(int(time.time() * 1000))
    data_param = json.dumps({"mode": "pc", "protocolVersion": "2.0"})

    sign = calculate_mtop_sign(token, t, MTOP_APP_KEY, data_param)

    params = {
        "jsv": "2.7.2",
        "appKey": MTOP_APP_KEY,
        "t": t,
        "sign": sign,
        "api": MTOP_API,
        "v": "1.0",
        "type": "originaljson",
        "dataType": "json",
    }

    try:
        resp = session.post(
            MTOP_URL,
            params=params,
            data={"data": data_param},
            headers=DEFAULT_HEADERS,
            cookies=cookie_dict,
            timeout=timeout
        )
        duration = round(time.perf_counter() - t_start, 2)
        data_bytes = len(resp.content)

        # Cập nhật _m_h5_tk nếu server trả cookie mới
        if "_m_h5_tk" in resp.cookies:
            cookie_dict["_m_h5_tk"] = resp.cookies["_m_h5_tk"]
            update_saved_cookie("_m_h5_tk", resp.cookies["_m_h5_tk"])
        if "_m_h5_tk_enc" in resp.cookies:
            cookie_dict["_m_h5_tk_enc"] = resp.cookies["_m_h5_tk_enc"]
            update_saved_cookie("_m_h5_tk_enc", resp.cookies["_m_h5_tk_enc"])

        try:
            res_json = resp.json()
        except Exception:
            return {"status": "fallback_needed", "duration": duration, "data_bytes": data_bytes}

        ret = res_json.get("ret", [])
        ret_str = " ".join(ret) if isinstance(ret, list) else str(ret)

        # 1. Phát hiện Cookie/Session hết hạn
        if "FAIL_SYS_SESSION_EXPIRED" in ret_str or "Session过期" in ret_str:
            return {
                "status": "need_login",
                "message": "Cookie Lazada đã hết hạn hoặc không hợp lệ. Vui lòng cập nhật cookie mới bằng /cookie.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes,
                "source": "mtop_api"
            }

        # 2. Xử lý Token hết hạn (thử lại 1 lần với token mới được cập nhật)
        if "FAIL_SYS_TOKEN_EXOIRED" in ret_str or "TOKEN_EXPIRED" in ret_str:
            new_token_cookie = cookie_dict.get("_m_h5_tk", "")
            new_token = new_token_cookie.split("_")[0] if new_token_cookie else ""
            if new_token and new_token != token:
                new_t = str(int(time.time() * 1000))
                new_sign = calculate_mtop_sign(new_token, new_t, MTOP_APP_KEY, data_param)
                params["t"] = new_t
                params["sign"] = new_sign
                resp2 = session.post(
                    MTOP_URL,
                    params=params,
                    data={"data": data_param},
                    headers=DEFAULT_HEADERS,
                    cookies=cookie_dict,
                    timeout=timeout
                )
                duration = round(time.perf_counter() - t_start, 2)
                data_bytes += len(resp2.content)
                res_json = resp2.json()

        # 3. Trích xuất dữ liệu thành công
        data_block = res_json.get("data", {})
        mod_data = {}
        hierarchy = None
        if isinstance(data_block, dict):
            if "module" in data_block and isinstance(data_block["module"], dict):
                mod_data = data_block["module"].get("data", {})
                hierarchy = data_block["module"].get("hierarchy")
            elif "data" in data_block and isinstance(data_block["data"], dict):
                mod_data = data_block["data"]
                hierarchy = data_block.get("hierarchy")
            else:
                mod_data = data_block

        products = []
        if mod_data:
            products, summary = extract_cart_from_modules(mod_data, hierarchy=hierarchy)
            if products:
                return {
                    "status": "ok",
                    "message": f"[API] Đã quét thành công {len(products)} phân loại sản phẩm qua Cart API.",
                    "products": products,
                    "summary": summary,
                    "duration": duration,
                    "data_bytes": data_bytes,
                    "source": "mtop_api"
                }

        # Nếu không có item và ret là SUCCESS thì có thể giỏ trống
        if "SUCCESS" in ret_str and not products:
            return {
                "status": "empty",
                "message": "Giỏ hàng hiện đang trống.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes,
                "source": "mtop_api"
            }

        return {"status": "fallback_needed", "duration": duration, "data_bytes": data_bytes}

    except Exception as e:
        logger.debug(f"mtop API error: {e}")
        return {"status": "fallback_needed", "duration": round(time.perf_counter() - t_start, 2), "data_bytes": 0}


def fetch_cart_via_page_html(cookie_dict: Dict[str, str], timeout: float = 10.0) -> Dict[str, Any]:
    """
    Phương án dự phòng 1: Gửi 1 HTTP GET request duy nhất tới trang giỏ hàng (https://cart.lazada.vn/cart)
    và trích xuất window.__initData__ trực tiếp từ HTML mà KHÔNG CẦN mở trình duyệt.
    """
    t_start = time.perf_counter()
    session = get_api_session()

    try:
        resp = session.get(
            CART_PAGE_URL,
            headers=PAGE_HEADERS,
            cookies=cookie_dict,
            timeout=timeout,
            allow_redirects=True
        )
        duration = round(time.perf_counter() - t_start, 2)
        data_bytes = len(resp.content)

        # Kiểm tra nếu bị chuyển hướng sang trang đăng nhập
        cur_url = resp.url.lower()
        if "member.lazada.vn" in cur_url or "login" in cur_url:
            return {
                "status": "need_login",
                "message": "Cookie Lazada đã hết hạn hoặc không hợp lệ. Vui lòng cập nhật cookie mới bằng /cookie.",
                "products": [],
                "summary": {},
                "duration": duration,
                "data_bytes": data_bytes,
                "source": "html_get"
            }

        # Trích xuất window.__initData__
        m = re.search(r'window\.__initData__\s*=\s*(\{[\s\S]*?\});\s*(?:</script>|\n)', resp.text)
        if not m:
            m = re.search(r'window\.__initData__\s*=\s*(\{.*?\});', resp.text)

        if m:
            try:
                init_data = json.loads(m.group(1))
                module_obj = init_data.get("module", {})
                mod_data = module_obj.get("data", {})
                hierarchy = module_obj.get("hierarchy")
                if mod_data:
                    products, summary = extract_cart_from_modules(mod_data, hierarchy=hierarchy)
                    if products:
                        return {
                            "status": "ok",
                            "message": f"[HTML-API] Đã quét {len(products)} phân loại sản phẩm từ Cart HTML.",
                            "products": products,
                            "summary": summary,
                            "duration": duration,
                            "data_bytes": data_bytes,
                            "source": "html_get"
                        }
                    else:
                        return {
                            "status": "empty",
                            "message": "Giỏ hàng hiện đang trống.",
                            "products": [],
                            "summary": {},
                            "duration": duration,
                            "data_bytes": data_bytes,
                            "source": "html_get"
                        }
            except Exception:
                pass

        return {"status": "fallback_needed", "duration": duration, "data_bytes": data_bytes}

    except Exception as e:
        logger.debug(f"fetch_cart_via_page_html error: {e}")
        return {"status": "fallback_needed", "duration": round(time.perf_counter() - t_start, 2), "data_bytes": 0}


def scrape_cart_via_requests(timeout: float = 8.0) -> Dict[str, Any]:
    """
    Hàm tổng hợp quét giỏ hàng bằng HTTP requests:
    1. Kiểm tra tồn tại file cookie.
    2. Thử qua Mtop API (siêu nhẹ, < 0.2s).
    3. Nếu cần, thử qua Cart Page HTML GET (siêu nhanh, < 0.4s).
    4. Trả về status 'ok', 'need_login', 'empty' hoặc 'fallback_needed' (để chuyển sang Selenium).
    """
    if not os.path.exists(COOKIES_FILE):
        return {
            "status": "need_login",
            "message": "Chưa có cookie. Hãy nạp cookie Lazada qua file cookie.json hoặc lệnh /cookie",
            "products": [],
            "summary": {},
            "duration": 0.0,
            "data_bytes": 0
        }

    cookie_dict = load_cookie_dict()
    if not cookie_dict:
        return {
            "status": "need_login",
            "message": "File cookie trống. Vui lòng nạp lại qua /cookie",
            "products": [],
            "summary": {},
            "duration": 0.0,
            "data_bytes": 0
        }

    # 1. Thử gọi qua Mtop API trước
    mtop_res = fetch_cart_via_mtop(cookie_dict, timeout=timeout)
    if mtop_res.get("status") in ("ok", "need_login", "empty"):
        return mtop_res

    # 2. Thử dự phòng qua GET HTML giỏ hàng
    html_res = fetch_cart_via_page_html(cookie_dict, timeout=timeout)
    if html_res.get("status") in ("ok", "need_login", "empty"):
        return html_res

    # Nếu cả 2 đều không thành công, trả về fallback_needed để Selenium xử lý tiếp
    return {
        "status": "fallback_needed",
        "duration": mtop_res.get("duration", 0.0) + html_res.get("duration", 0.0),
        "data_bytes": mtop_res.get("data_bytes", 0) + html_res.get("data_bytes", 0)
    }
