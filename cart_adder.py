"""
Lazada Cart Adder Module
Hỗ trợ:
- Tự động nhận diện link sản phẩm Lazada (bao gồm link web lazada.vn/products/... và link rút gọn s.lazada.vn/...)
- Tải thông tin chi tiết sản phẩm: Tên, Giá, Ảnh, Danh sách tất cả phân loại (SKU)
- Tự động click phân loại được chọn và thêm vào giỏ hàng
"""

import json
import logging
import re
import time
import urllib.request
from typing import Optional, List, Dict, Any

from anti_detect import create_stealth_driver, load_cookies, save_cookies, safe_quit

logger = logging.getLogger(__name__)

LAZADA_URL_REGEX = r'https?://(?:[a-zA-Z0-9_\-]+\.)?lazada\.vn/[^\s]+'


def extract_lazada_url(text: str) -> Optional[str]:
    """Tìm và bóc tách link Lazada trong nội dung tin nhắn"""
    if not text:
        return None
    match = re.search(LAZADA_URL_REGEX, text)
    if match:
        url = match.group(0).rstrip('.,;()[]"\'')
        return resolve_lazada_url(url)
    return None


def resolve_lazada_url(url: str) -> str:
    """Giải mã link rút gọn s.lazada.vn về link sản phẩm gốc"""
    url = url.strip()
    if "s.lazada.vn" in url:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                real_url = resp.geturl()
                if "lazada.vn" in real_url:
                    return real_url
        except Exception as e:
            logger.debug(f"Không giải mã được link s.lazada.vn qua HTTP redirect: {e}")
    return url


def fetch_product_details(url: str, headless: bool = True) -> Dict[str, Any]:
    """
    Truy cập trang sản phẩm Lazada để trích xuất:
    - Tên sản phẩm
    - Giá bán hiện tại & giá gốc
    - Ảnh đại diện
    - Danh sách các phân loại (SKU / Màu sắc / Kích thước)
    """
    driver = None
    try:
        driver = create_stealth_driver(headless=headless)
        load_cookies(driver)
        driver.get(url)
        time.sleep(3.5)

        # Trích xuất dữ liệu chi tiết
        result = driver.execute_script('''
            var res = {
                title: '',
                price: '',
                originalPrice: '',
                image: '',
                variations: [],
                isOutOfStock: false,
                isAvailable: true
            };

            // 1. Kiểm tra nếu sản phẩm bị gỡ hoặc không tồn tại
            var bodyText = document.body ? document.body.innerText : '';
            if (bodyText.indexOf("Sorry! This product is no longer available") !== -1 ||
                bodyText.indexOf("Sản phẩm này không còn tồn tại") !== -1) {
                res.isAvailable = false;
                return res;
            }

            // 2. Trích xuất Schema JSON-LD
            var scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (var i = 0; i < scripts.length; i++) {
                try {
                    var data = JSON.parse(scripts[i].innerText);
                    if (data['@type'] === 'Product') {
                        res.title = data.name || res.title;
                        if (data.image && data.image.length > 0) {
                            res.image = data.image[0];
                        }
                    }
                } catch(e) {}
            }

            // 3. Trích xuất Tên sản phẩm từ DOM nếu JSON-LD chưa có
            if (!res.title) {
                var titleEl = document.querySelector('.pdp-mod-product-badge-title, h1, .pdp-product-title');
                if (titleEl) res.title = titleEl.innerText.trim();
            }

            // 4. Trích xuất Giá sản phẩm
            var salePriceEl = document.querySelector('.pdp-v2-product-price-content-salePrice, .pdp-price_color_orange, .pdp-price');
            if (salePriceEl) res.price = salePriceEl.innerText.trim();

            var origPriceEl = document.querySelector('.pdp-v2-product-price-content-originalPrice, .pdp-price_type_deleted');
            if (origPriceEl) res.originalPrice = origPriceEl.innerText.trim();

            // 5. Trích xuất Phân loại (SKU)
            var seen = {};
            var skuElements = document.querySelectorAll('.sku-variable-name, .sku-variable-size, .sku-name, [class*="sku-variable-"]');
            for (var j = 0; j < skuElements.length; j++) {
                var el = skuElements[j];
                var name = (el.innerText || el.getAttribute('title') || '').trim();
                if (name && !seen[name] && name.length < 60 && name.indexOf('Quantity') === -1 && name.indexOf('Số lượng') === -1) {
                    seen[name] = true;
                    var isSelected = el.classList.contains('sku-variable-name-selected') ||
                                     el.classList.contains('selected') ||
                                     el.classList.contains('sku-variable-size-selected');
                    var isDisabled = el.classList.contains('disabled');
                    res.variations.push({
                        name: name,
                        selected: isSelected,
                        disabled: isDisabled
                    });
                }
            }

            // 6. Kiểm tra nút Mua / Thêm vào giỏ
            var addBtn = document.querySelector('button.add-to-cart-buy-now-btn, button.pdp-button_theme_orange, .pdp-button-add-to-cart');
            if (!addBtn) {
                res.isOutOfStock = true;
            }

            return res;
        ''')

        if not result or not result.get("isAvailable"):
            return {
                "status": "not_found",
                "message": "Sản phẩm này hiện không còn khả dụng hoặc đã bị gỡ trên Lazada.",
                "url": url
            }

        title = result.get("title") or "Sản phẩm Lazada"
        price = result.get("price") or "N/A"
        original_price = result.get("originalPrice") or ""
        variations = result.get("variations") or []
        image = result.get("image") or ""
        if image.startswith("//"):
            image = "https:" + image

        return {
            "status": "ok",
            "title": title,
            "price": price,
            "original_price": original_price,
            "image": image,
            "variations": variations,
            "url": driver.current_url or url
        }

    except Exception as e:
        logger.error(f"Lỗi khi đọc chi tiết sản phẩm: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Lỗi kết nối Lazada: {e}",
            "url": url
        }
    finally:
        safe_quit(driver)


def add_sku_to_cart(url: str, sku_name: Optional[str] = None, headless: bool = True) -> Dict[str, Any]:
    """
    Mở trang sản phẩm, click phân loại SKU tương ứng (nếu có) và bấm 'Thêm vào giỏ hàng'
    """
    driver = None
    try:
        driver = create_stealth_driver(headless=headless)
        if not load_cookies(driver):
            return {
                "status": "need_login",
                "message": "Không nạp được cookie đăng nhập. Vui lòng nạp lại cookie Lazada qua lệnh /cookie."
            }

        driver.get(url)
        time.sleep(3.5)

        # 1. Nếu có phân loại, click chọn phân loại đó
        if sku_name:
            clicked = driver.execute_script('''
                var target = arguments[0];
                var items = document.querySelectorAll('.sku-variable-name, .sku-variable-size, .sku-name, [class*="sku-variable-"]');
                for (var i = 0; i < items.length; i++) {
                    var el = items[i];
                    var txt = (el.innerText || el.getAttribute('title') || '').trim();
                    if (txt === target) {
                        el.click();
                        return true;
                    }
                }
                return false;
            ''', sku_name)
            time.sleep(1.2)

        # 2. Click nút 'Add to Cart' / 'Thêm vào giỏ hàng'
        add_result = driver.execute_script('''
            var btns = document.querySelectorAll('button, a, div[role="button"]');
            for (var i = 0; i < btns.length; i++) {
                var b = btns[i];
                var txt = (b.innerText || '').toLowerCase();
                if (txt.indexOf('add to cart') !== -1 || txt.indexOf('thêm vào giỏ') !== -1) {
                    b.click();
                    return { clicked: true, text: b.innerText.trim() };
                }
            }
            return { clicked: false };
        ''')

        if not add_result.get("clicked"):
            return {
                "status": "error",
                "message": "Không tìm thấy nút 'Thêm vào giỏ hàng' (sản phẩm có thể đã hết hàng)."
            }

        # 3. Đợi hộp thoại xác nhận thành công xuất hiện
        time.sleep(2.0)
        success_check = driver.execute_script('''
            var bodyText = document.body ? document.body.innerText : '';
            var hasSuccess = bodyText.indexOf('Added to cart successfully') !== -1 ||
                             bodyText.indexOf('Thêm vào giỏ hàng thành công') !== -1 ||
                             bodyText.indexOf('Đã thêm vào giỏ hàng') !== -1;
            var dialog = document.querySelector('.next-dialog, .cart-success-dialog, .pdp-dialog');
            return {
                success: hasSuccess || !!dialog
            };
        ''')

        save_cookies(driver)

        return {
            "status": "ok",
            "message": "Đã thêm sản phẩm vào giỏ hàng thành công!"
        }

    except Exception as e:
        logger.error(f"Lỗi khi thêm sản phẩm vào giỏ: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Lỗi thao tác: {e}"
        }
    finally:
        safe_quit(driver)
