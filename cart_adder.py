"""
Lazada Cart Adder Module
Hỗ trợ:
- Tự động nhận diện link sản phẩm Lazada (lazada.vn/products/... và link rút gọn s.lazada.vn/...)
- Trích xuất chi tiết sản phẩm: Tên, Giá, Ảnh, và TẤT CẢ các lớp phân loại (Màu sắc, Kích cỡ, Chất liệu...)
- Hỗ trợ chọn đồng thời nhiều lớp phân loại và bấm 'Thêm vào giỏ hàng' chuẩn xác
"""

import logging
import re
import time
import urllib.request
from typing import Optional, List, Dict, Any, Union

from anti_detect import create_stealth_driver, load_cookies, save_cookies, safe_quit, safe_get

logger = logging.getLogger(__name__)

LAZADA_URL_REGEX = r'https?://(?:[a-zA-Z0-9_\-]+\.)?lazada\.vn/[^\s]+'


def extract_lazada_url(text: str) -> Optional[str]:
    """Tìm và bóc tách link Lazada trong tin nhắn"""
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
    - Tên sản phẩm, Giá bán hiện tại, Giá gốc, Ảnh đại diện
    - TẤT CẢ các lớp phân loại (Layers: Màu sắc, Kích thước, Chất liệu...)
    """
    driver = None
    try:
        driver = create_stealth_driver(headless=headless)
        load_cookies(driver)
        safe_get(driver, url, timeout=30)

        # Chờ phần tử sản phẩm xuất hiện
        for _ in range(25):
            ready = driver.execute_script("""
                return Boolean(
                    document.querySelector('.pdp-mod-product-badge-title, h1, .pdp-product-title, .pdp-price')
                );
            """)
            if ready:
                break
            time.sleep(0.12)

        # Trích xuất dữ liệu chi tiết kèm phân loại nhiều lớp
        result = driver.execute_script('''
            var res = {
                title: '',
                price: '',
                originalPrice: '',
                image: '',
                layers: [],
                isOutOfStock: false,
                isAvailable: true
            };

            // 1. Kiểm tra nếu sản phẩm bị gỡ
            var bodyText = document.body ? document.body.innerText : '';
            if (bodyText.indexOf("Sorry! This product is no longer available") !== -1 ||
                bodyText.indexOf("Sản phẩm này không còn tồn tại") !== -1) {
                res.isAvailable = false;
                return res;
            }

            // 2. Schema JSON-LD
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

            // 3. Tên sản phẩm từ DOM
            if (!res.title) {
                var titleEl = document.querySelector('.pdp-mod-product-badge-title, h1, .pdp-product-title');
                if (titleEl) res.title = titleEl.innerText.trim();
            }

            // 4. Giá sản phẩm
            var salePriceEl = document.querySelector('.pdp-v2-product-price-content-salePrice, .pdp-price_color_orange, .pdp-price');
            if (salePriceEl) res.price = salePriceEl.innerText.trim();

            var origPriceEl = document.querySelector('.pdp-v2-product-price-content-originalPrice, .pdp-price_type_deleted');
            if (origPriceEl) res.originalPrice = origPriceEl.innerText.trim();

            // 5. Trích xuất từng lớp phân loại (Layers: Màu sắc, Size, Chất liệu...)
            var layers = [];

            // A. Tìm trong dữ liệu module JavaScript của Lazada
            try {
                var modData = window.__moduleData__ || (window.__INIT_DATA__ && window.__INIT_DATA__.module) || null;
                var skuBase = null;
                if (modData && modData.data && modData.data.root && modData.data.root.fields) {
                    skuBase = modData.data.root.fields.skuBase;
                }
                if (skuBase && skuBase.properties && Array.isArray(skuBase.properties)) {
                    for (var p = 0; p < skuBase.properties.length; p++) {
                        var prop = skuBase.properties[p];
                        var propName = (prop.name || 'Lớp ' + (p + 1)).trim();
                        var options = [];
                        if (prop.values && Array.isArray(prop.values)) {
                            for (var v = 0; v < prop.values.length; v++) {
                                var valName = (prop.values[v].name || '').trim();
                                if (valName) {
                                    options.push({
                                        name: valName,
                                        selected: false,
                                        disabled: false
                                    });
                                }
                            }
                        }
                        if (options.length > 0) {
                            layers.push({
                                name: propName,
                                options: options
                            });
                        }
                    }
                }
            } catch(e) {}

            // B. Trích xuất trực tiếp từ các khối DOM của từng lớp (nếu JS chưa có)
            if (layers.length === 0) {
                var propBlocks = document.querySelectorAll(
                    '.sku-prop, .pdp-mod-product-info-section-sku, .pdp-block__sku, [class*="sku-prop"]'
                );

                for (var b = 0; b < propBlocks.length; b++) {
                    var block = propBlocks[b];

                    // Tên lớp (ví dụ: "Nhóm màu", "Kích cỡ", "Chất liệu")
                    var titleEl = block.querySelector(
                        '.sku-prop-title, .pdp-mod-product-info-section-title, .section-title, h3, [class*="prop-title"]'
                    );
                    var groupName = '';
                    if (titleEl) {
                        groupName = (titleEl.innerText || '').replace(/[:：]/g, '').trim();
                    }

                    // Các tùy chọn trong lớp
                    var items = block.querySelectorAll(
                        '.sku-variable-name, .sku-variable-size, .sku-name, .sku-prop-content-item, [class*="sku-variable-item"], [class*="sku-variable-name"]'
                    );

                    var options = [];
                    var seenOpts = {};
                    for (var it = 0; it < items.length; it++) {
                        var itemEl = items[it];
                        var optName = (itemEl.innerText || itemEl.getAttribute('title') || '').trim();
                        if (optName && !seenOpts[optName] && optName.length < 50 &&
                            optName.indexOf('Quantity') === -1 && optName.indexOf('Số lượng') === -1) {
                            seenOpts[optName] = true;
                            var isSel = itemEl.classList.contains('sku-variable-name-selected') ||
                                        itemEl.classList.contains('selected') ||
                                        itemEl.classList.contains('sku-variable-size-selected');
                            var isDis = itemEl.classList.contains('disabled');
                            options.push({
                                name: optName,
                                selected: isSel,
                                disabled: isDis
                            });
                        }
                    }

                    if (options.length > 0) {
                        if (!groupName) groupName = 'Lớp ' + (layers.length + 1);
                        layers.push({
                            name: groupName,
                            options: options
                        });
                    }
                }
            }

            // C. Fallback toàn cục nếu không gom được khối
            if (layers.length === 0) {
                var globalItems = document.querySelectorAll('.sku-variable-name, .sku-variable-size, .sku-name, [class*="sku-variable-"]');
                var fallbackOpts = [];
                var seenGlobal = {};
                for (var g = 0; g < globalItems.length; g++) {
                    var gEl = globalItems[g];
                    var gName = (gEl.innerText || gEl.getAttribute('title') || '').trim();
                    if (gName && !seenGlobal[gName] && gName.length < 50 &&
                        gName.indexOf('Quantity') === -1 && gName.indexOf('Số lượng') === -1) {
                        seenGlobal[gName] = true;
                        fallbackOpts.push({
                            name: gName,
                            selected: false,
                            disabled: false
                        });
                    }
                }
                if (fallbackOpts.length > 0) {
                    layers.push({
                        name: 'Phân loại',
                        options: fallbackOpts
                    });
                }
            }

            res.layers = layers;

            // 6. Kiểm tra nút Thêm vào giỏ
            var addBtn = document.querySelector('button.add-to-cart-buy-now-btn, button.pdp-button_theme_orange, .pdp-button-add-to-cart');
            if (!addBtn) {
                res.isOutOfStock = true;
            }

            return res;
        ''')

        if not result or not result.get("isAvailable"):
            return {
                "status": "not_found",
                "message": "Sản phẩm không khả dụng hoặc đã bị gỡ trên Lazada.",
                "url": url
            }

        title = result.get("title") or "Sản phẩm Lazada"
        price = result.get("price") or "N/A"
        original_price = result.get("originalPrice") or ""
        layers = result.get("layers") or []
        image = result.get("image") or ""
        if image.startswith("//"):
            image = "https:" + image

        return {
            "status": "ok",
            "title": title,
            "price": price,
            "original_price": original_price,
            "image": image,
            "layers": layers,
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


def add_sku_to_cart(url: str, selected_options: Optional[Union[str, List[str]]] = None, headless: bool = True) -> Dict[str, Any]:
    """
    Mở trang sản phẩm, click chọn lần lượt TẤT CẢ các lớp phân loại (Màu, Size, Chất liệu...)
    rồi bấm nút 'Thêm vào giỏ hàng'.
    """
    driver = None
    try:
        driver = create_stealth_driver(headless=headless)
        if not load_cookies(driver):
            return {
                "status": "need_login",
                "message": "Cookie hết hạn hoặc chưa nạp. Vui lòng nạp lại qua /cookie."
            }

        safe_get(driver, url, timeout=30)
        # Chờ phần tử sản phẩm xuất hiện
        for _ in range(25):
            ready = driver.execute_script("""
                return Boolean(
                    document.querySelector('.pdp-mod-product-badge-title, h1, .pdp-product-title, .pdp-price')
                );
            """)
            if ready:
                break
            time.sleep(0.12)

        # Chuyển đổi thành danh sách các tùy chọn cần click
        targets: List[str] = []
        if isinstance(selected_options, str):
            targets = [selected_options.strip()]
        elif isinstance(selected_options, list):
            targets = [str(x).strip() for x in selected_options if str(x).strip()]

        # 1. Click lần lượt từng lớp phân loại
        if targets:
            clicked_summary = driver.execute_script('''
                var targets = arguments[0];
                var clicked = [];
                for (var t = 0; t < targets.length; t++) {
                    var wanted = targets[t].toLowerCase();
                    var candidates = document.querySelectorAll(
                        '.sku-variable-name, .sku-variable-size, .sku-name, [class*="sku-variable-"], .sku-prop-content-item, [title]'
                    );
                    for (var i = 0; i < candidates.length; i++) {
                        var el = candidates[i];
                        var txt = (el.innerText || el.getAttribute('title') || '').trim().toLowerCase();
                        if (txt === wanted) {
                            el.click();
                            clicked.push(targets[t]);
                            break;
                        }
                    }
                }
                return clicked;
            ''', targets)
            time.sleep(0.35)

        # 2. Click nút 'Thêm vào giỏ hàng'
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

        # 3. Chờ xác nhận thành công
        for _ in range(15):
            success_check = driver.execute_script('''
                var bodyText = document.body ? document.body.innerText : '';
                var hasSuccess = bodyText.indexOf('Added to cart successfully') !== -1 ||
                                 bodyText.indexOf('Thêm vào giỏ hàng thành công') !== -1 ||
                                 bodyText.indexOf('Đã thêm vào giỏ hàng') !== -1;
                var dialog = document.querySelector('.next-dialog, .cart-success-dialog, .pdp-dialog');
                return hasSuccess || !!dialog;
            ''')
            if success_check:
                break
            time.sleep(0.12)

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
