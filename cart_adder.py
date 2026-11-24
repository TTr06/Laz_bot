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


def clean_opt_name(text: str) -> str:
    """Làm sạch tên tùy chọn phân loại (loại bỏ xuống dòng, giá tiền phụ, nhãn hết hàng dính kèm)"""
    if not text:
        return ""
    first_line = text.strip().split("\n")[0].strip()
    clean = re.sub(r'\s*[\d\.,]+\s*(?:₫|đ|vnd|k)\b.*$', '', first_line, flags=re.IGNORECASE).strip()
    clean = re.sub(r'\s*[\(\[]\s*(?:hết hàng|tạm hết|out of stock)\s*[\)\]]', '', clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean


def clean_and_deduplicate_layers(raw_layers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Chuẩn hóa và khử triệt để trùng lặp giữa các lớp phân loại (Layers):
    - Khử các lớp trùng lặp nội dung do DOM lồng nhau hoặc modal drawer.
    - Loại bỏ các lớp rác (Bảng kích cỡ, hướng dẫn chọn size, số lượng...).
    - Khử trùng lặp các options trong cùng 1 lớp.
    """
    cleaned_layers: List[Dict[str, Any]] = []
    seen_option_fingerprints = set()
    seen_layer_names = set()

    for layer in raw_layers:
        raw_name = (layer.get("name") or "").strip()
        # Loại bỏ các tiền tố/hậu tố thừa (ví dụ: "Nhóm màu: Đen" -> "Nhóm màu")
        clean_name = re.sub(r'[:：].*$', '', raw_name).strip()
        if not clean_name:
            clean_name = f"Lớp {len(cleaned_layers) + 1}"

        lower_name = clean_name.lower()
        if any(w in lower_name for w in ["bảng kích cỡ", "size chart", "size guide", "hướng dẫn chọn size", "số lượng", "quantity"]):
            continue

        raw_opts = layer.get("options") or []
        valid_opts: List[Dict[str, Any]] = []
        seen_opt_names = set()

        for opt in raw_opts:
            if isinstance(opt, str):
                o_name = opt
            elif isinstance(opt, dict):
                o_name = opt.get("name", "")
            else:
                continue

            o_clean = clean_opt_name(o_name)
            o_lower = o_clean.lower()
            if not o_clean or len(o_clean) > 60 or o_lower in seen_opt_names:
                continue
            if any(w in o_lower for w in ["bảng kích cỡ", "size chart", "size guide", "hướng dẫn", "quantity", "số lượng", "xem thêm"]):
                continue

            seen_opt_names.add(o_lower)
            is_sel = opt.get("selected", False) if isinstance(opt, dict) else False
            is_dis = opt.get("disabled", False) if isinstance(opt, dict) else False
            valid_opts.append({
                "name": o_clean,
                "selected": is_sel,
                "disabled": is_dis
            })

        if not valid_opts:
            continue

        # Fingerprint đại diện cho tập options đã sắp xếp
        fingerprint = tuple(sorted(o["name"].lower() for o in valid_opts))

        # Nếu tập options đã xuất hiện ở lớp trước -> Trùng lặp hoàn toàn -> Bỏ qua
        if fingerprint in seen_option_fingerprints:
            continue

        # Nếu trùng tên lớp và có overlap tùy chọn -> Bỏ qua
        if lower_name in seen_layer_names:
            overlap = False
            for exist_layer in cleaned_layers:
                if exist_layer["name"].lower() == lower_name:
                    exist_opts = {o["name"].lower() for o in exist_layer["options"]}
                    cur_opts = {o["name"].lower() for o in valid_opts}
                    if exist_opts & cur_opts:
                        overlap = True
                        break
            if overlap:
                continue

        seen_option_fingerprints.add(fingerprint)
        seen_layer_names.add(lower_name)

        cleaned_layers.append({
            "name": clean_name,
            "options": valid_opts
        })

    return cleaned_layers


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

            // A. Tìm sâu trong dữ liệu module JavaScript của Lazada (Deep search)
            function getSkuBase() {
                try {
                    if (window.__moduleData__) {
                        var md = window.__moduleData__;
                        if (md.data && md.data.root && md.data.root.fields && md.data.root.fields.skuBase) return md.data.root.fields.skuBase;
                        if (md.data && md.data.fields && md.data.fields.skuBase) return md.data.fields.skuBase;
                        if (md.fields && md.fields.skuBase) return md.fields.skuBase;
                    }
                } catch(e) {}
                try {
                    if (window.__INIT_DATA__) {
                        var id = window.__INIT_DATA__;
                        if (id.data && id.data.root && id.data.root.fields && id.data.root.fields.skuBase) return id.data.root.fields.skuBase;
                        if (id.data && id.data.fields && id.data.fields.skuBase) return id.data.fields.skuBase;
                        if (id.module && id.module.data && id.module.data.root && id.module.data.root.fields && id.module.data.root.fields.skuBase) return id.module.data.root.fields.skuBase;
                        if (id.module && id.module.data && id.module.data.fields && id.module.data.fields.skuBase) return id.module.data.fields.skuBase;
                    }
                } catch(e) {}
                try {
                    if (window.pageData && window.pageData.skuBase) return window.pageData.skuBase;
                    if (window.g_config && window.g_config.skuBase) return window.g_config.skuBase;
                } catch(e) {}
                return null;
            }

            try {
                var skuBase = getSkuBase();
                if (skuBase && skuBase.properties && Array.isArray(skuBase.properties)) {
                    var seenPropNames = {};
                    for (var p = 0; p < skuBase.properties.length; p++) {
                        var prop = skuBase.properties[p];
                        var pName = (prop.name || '').replace(/[:：]/g, '').trim();
                        if (!pName) pName = 'Lớp ' + (layers.length + 1);
                        var pLower = pName.toLowerCase();
                        if (seenPropNames[pLower]) continue;

                        var options = [];
                        var seenOpt = {};
                        if (prop.values && Array.isArray(prop.values)) {
                            for (var v = 0; v < prop.values.length; v++) {
                                var vName = (prop.values[v].name || '').trim();
                                if (vName && !seenOpt[vName.toLowerCase()]) {
                                    seenOpt[vName.toLowerCase()] = true;
                                    options.push({
                                        name: vName,
                                        selected: false,
                                        disabled: false
                                    });
                                }
                            }
                        }
                        if (options.length > 0) {
                            seenPropNames[pLower] = true;
                            layers.push({
                                name: pName,
                                options: options
                            });
                        }
                    }
                }
            } catch(e) {}

            // B. Trích xuất trực tiếp từ các khối DOM của từng lớp (nếu JS chưa có)
            if (layers.length === 0) {
                var candidateBlocks = document.querySelectorAll(
                    '.sku-prop, .pdp-mod-product-info-section-sku > div, .pdp-block__sku'
                );
                if (candidateBlocks.length === 0) {
                    candidateBlocks = document.querySelectorAll('[class*="sku-prop"]');
                }

                // Lọc Top-level blocks: Loại bỏ phần tử con bị lồng bên trong block khác và popup/dialog
                var topBlocks = [];
                for (var i = 0; i < candidateBlocks.length; i++) {
                    var b = candidateBlocks[i];
                    var cls = (b.className || '').toString();
                    if (cls.indexOf('sku-prop-content-item') !== -1 || 
                        cls.indexOf('sku-prop-title') !== -1 ||
                        cls.indexOf('sku-variable-') !== -1) {
                        continue;
                    }
                    if (b.closest('.next-dialog, .pdp-drawer, .sku-drawer, [style*="display: none"], [style*="display:none"], [hidden]')) {
                        continue;
                    }
                    var isChild = false;
                    for (var j = 0; j < candidateBlocks.length; j++) {
                        if (i !== j && candidateBlocks[j].contains(b)) {
                            isChild = true;
                            break;
                        }
                    }
                    if (!isChild) {
                        topBlocks.push(b);
                    }
                }

                var seenDomKeys = {};
                for (var bIdx = 0; bIdx < topBlocks.length; bIdx++) {
                    var block = topBlocks[bIdx];

                    // Tên lớp
                    var titleEl = block.querySelector('.sku-prop-title, .pdp-mod-product-info-section-title, .section-title, h3, [class*="prop-title"]');
                    var groupName = '';
                    if (titleEl) {
                        var fullT = titleEl.innerText || '';
                        var subVal = titleEl.querySelector('.sku-name, [class*="selected"], span:not(:first-child)');
                        if (subVal) fullT = fullT.replace(subVal.innerText, '');
                        groupName = fullT.split(/[:：]/)[0].trim();
                    }

                    // Các tùy chọn trong lớp
                    var items = block.querySelectorAll('.sku-variable-name, .sku-variable-size, .sku-name, .sku-prop-content-item, [class*="sku-variable-item"]');
                    var options = [];
                    var seenOpts = {};
                    for (var it = 0; it < items.length; it++) {
                        var itemEl = items[it];
                        var optName = itemEl.getAttribute('title') || '';
                        if (!optName) {
                            var imgEl = itemEl.querySelector('img');
                            if (imgEl) optName = imgEl.getAttribute('alt') || imgEl.getAttribute('title') || '';
                        }
                        if (!optName) {
                            optName = (itemEl.innerText || '').split('\n')[0];
                        }
                        optName = optName.trim();
                        var optLower = optName.toLowerCase();

                        if (!optName || optName.length > 60 || seenOpts[optLower] ||
                            optLower.indexOf('quantity') !== -1 || optLower.indexOf('số lượng') !== -1 ||
                            optLower.indexOf('bảng kích cỡ') !== -1 || optLower.indexOf('size chart') !== -1 ||
                            optLower.indexOf('hướng dẫn') !== -1) {
                            continue;
                        }

                        seenOpts[optLower] = true;
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

                    if (options.length > 0) {
                        if (!groupName) groupName = 'Lớp ' + (layers.length + 1);
                        var optKey = options.map(function(o){ return o.name.toLowerCase(); }).sort().join('|');
                        if (!seenDomKeys[optKey]) {
                            seenDomKeys[optKey] = true;
                            layers.push({
                                name: groupName,
                                options: options
                            });
                        }
                    }
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
        raw_layers = result.get("layers") or []
        layers = clean_and_deduplicate_layers(raw_layers)
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
                    var wanted = targets[t].trim().toLowerCase();
                    var candidates = document.querySelectorAll(
                        '.sku-variable-name, .sku-variable-size, .sku-name, [class*="sku-variable-"], .sku-prop-content-item, [title]'
                    );
                    for (var i = 0; i < candidates.length; i++) {
                        var el = candidates[i];
                        if (el.offsetParent === null) continue;

                        var txt = el.getAttribute('title') || '';
                        if (!txt) {
                            var img = el.querySelector('img');
                            if (img) txt = img.getAttribute('alt') || img.getAttribute('title') || '';
                        }
                        if (!txt) {
                            txt = (el.innerText || '').split('\n')[0];
                        }
                        txt = txt.trim().toLowerCase();

                        if (txt === wanted || (txt.length >= 3 && wanted.indexOf(txt) === 0) || (wanted.length >= 3 && txt.indexOf(wanted) === 0)) {
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
