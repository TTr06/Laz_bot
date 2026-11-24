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
    """Làm sạch tên tùy chọn phân loại (loại bỏ nhãn hết hàng, chuẩn hóa khoảng trắng)"""
    if not text:
        return ""
    first_line = str(text).strip().split("\n")[0].strip()
    clean = re.sub(r'\s*[\(\[]\s*(?:hết hàng|tạm hết|out of stock)\s*[\)\]]', '', first_line, flags=re.IGNORECASE).strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean


def clean_and_deduplicate_layers(raw_layers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Chuẩn hóa và khử trùng lặp giữa các lớp phân loại (Layers):
    - Giữ trọn vẹn toàn bộ các tùy chọn và thông số kỹ thuật hợp lệ.
    - Loại bỏ các lớp rác trợ giúp (Bảng kích cỡ, hướng dẫn chọn size, số lượng...).
    - Khử trùng lặp giữa các khối clone do DOM modal drawer sinh ra.
    """
    cleaned_layers: List[Dict[str, Any]] = []
    seen_layer_keys = set()

    for idx, layer in enumerate(raw_layers):
        raw_name = (layer.get("name") or "").strip()
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
                is_sel = False
                is_dis = False
            elif isinstance(opt, dict):
                o_name = opt.get("name", "")
                is_sel = opt.get("selected", False)
                is_dis = opt.get("disabled", False)
            else:
                continue

            o_clean = clean_opt_name(o_name)
            o_lower = o_clean.lower()
            if not o_clean or len(o_clean) > 120 or o_lower in seen_opt_names:
                continue
            if o_lower in ["bảng kích cỡ", "size chart", "size guide", "hướng dẫn chọn size", "hướng dẫn", "xem thêm", "quantity", "số lượng"]:
                continue

            seen_opt_names.add(o_lower)
            valid_opts.append({
                "name": o_clean,
                "selected": is_sel,
                "disabled": is_dis
            })

        if not valid_opts:
            continue

        # Chỉ loại bỏ nếu trùng cả tên lớp lẫn toàn bộ tập tùy chọn đã sắp xếp
        fingerprint = (lower_name, tuple(sorted(o["name"].lower() for o in valid_opts)))
        if fingerprint in seen_layer_keys:
            continue
        seen_layer_keys.add(fingerprint)

        cleaned_layers.append({
            "name": clean_name,
            "options": valid_opts
        })

    return cleaned_layers


def generate_combinations(layers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tạo danh sách các tổ hợp phân loại (Cartesian product) từ các lớp phân loại"""
    if not layers:
        return []
    import itertools
    layer_options = [[o["name"] for o in lyr.get("options", []) if o.get("name")] for lyr in layers]
    layer_options = [opts for opts in layer_options if opts]
    if not layer_options:
        return []

    combos = []
    for prod in itertools.product(*layer_options):
        combos.append({
            "name": " / ".join(prod),
            "parts": list(prod),
            "price": "",
            "inStock": True
        })
        if len(combos) >= 60:
            break
    return combos


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

        # Trích xuất dữ liệu chi tiết kèm phân loại nhiều lớp và tổ hợp SKU
        result = driver.execute_script(r'''
            var res = {
                title: '',
                price: '',
                originalPrice: '',
                image: '',
                layers: [],
                combinations: [],
                isOutOfStock: false,
                isAvailable: true
            };

            try {
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

                // 5. Trích xuất phân loại (Layers & Combinations)
                var layers = [];
                var combinations = [];

                // A. Tìm sâu trong toàn bộ dữ liệu JavaScript của Lazada
                function findSkuBaseDeep() {
                    var roots = [
                        window.__moduleData__,
                        window.__INIT_DATA__,
                        window.pageData,
                        window.g_config,
                        window.__INITIAL_DATA__,
                        window.__PRELOADED_STATE__,
                        window.__INITIAL_STATE__
                    ];

                    function searchObj(obj, depth) {
                        if (!obj || typeof obj !== 'object' || depth > 5) return null;
                        if (obj.skuBase && typeof obj.skuBase === 'object') return obj.skuBase;
                        if (Array.isArray(obj.properties) && obj.properties.length > 0 && Array.isArray(obj.skus)) {
                            return obj;
                        }
                        for (var k in obj) {
                            if (Object.prototype.hasOwnProperty.call(obj, k)) {
                                try {
                                    var val = obj[k];
                                    if (val && typeof val === 'object') {
                                        var found = searchObj(val, depth + 1);
                                        if (found) return found;
                                    }
                                } catch(e) {}
                            }
                        }
                        return null;
                    }

                    for (var r = 0; r < roots.length; r++) {
                        if (roots[r]) {
                            var foundRoot = searchObj(roots[r], 0);
                            if (foundRoot) return foundRoot;
                        }
                    }

                    // Tìm trong các thẻ <script>
                    var allScripts = document.querySelectorAll('script');
                    for (var s = 0; s < allScripts.length; s++) {
                        var txt = allScripts[s].innerText || '';
                        if (txt.indexOf('skuBase') !== -1 && txt.indexOf('properties') !== -1) {
                            try {
                                var parsed = JSON.parse(txt);
                                var foundScript = searchObj(parsed, 0);
                                if (foundScript) return foundScript;
                            } catch(e) {}
                            try {
                                var m = txt.match(/"skuBase"\s*:\s*(\{.*?"skus"\s*:\s*\[.*?\]\s*\})/s);
                                if (m && m[1]) {
                                    var parsedM = JSON.parse(m[1]);
                                    if (parsedM && Array.isArray(parsedM.properties)) return parsedM;
                                }
                            } catch(e) {}
                        }
                    }
                    return null;
                }

                try {
                    var skuBase = findSkuBaseDeep();
                    if (skuBase && skuBase.properties && Array.isArray(skuBase.properties) && skuBase.properties.length > 0) {
                        var valMap = {};
                        var propNames = {};

                        for (var p = 0; p < skuBase.properties.length; p++) {
                            var prop = skuBase.properties[p];
                            var pid = String(prop.pid || p);
                            var pName = (prop.name || '').replace(/[:：]/g, '').trim();
                            if (!pName) pName = 'Lớp ' + (layers.length + 1);
                            propNames[pid] = pName;

                            var options = [];
                            var seenOpt = {};
                            if (prop.values && Array.isArray(prop.values)) {
                                for (var v = 0; v < prop.values.length; v++) {
                                    var valObj = prop.values[v];
                                    var vid = String(valObj.vid || v);
                                    var vName = (valObj.name || '').trim();
                                    if (vName && !seenOpt[vName.toLowerCase()]) {
                                        seenOpt[vName.toLowerCase()] = true;
                                        valMap[pid + ':' + vid] = {
                                            name: vName,
                                            image: valObj.image || ''
                                        };
                                        options.push({
                                            id: vid,
                                            name: vName,
                                            image: valObj.image || '',
                                            selected: false,
                                            disabled: false
                                        });
                                    }
                                }
                            }
                            if (options.length > 0) {
                                layers.push({
                                    id: pid,
                                    name: pName,
                                    options: options
                                });
                            }
                        }

                        // Trích xuất danh sách tổ hợp phân loại (skus)
                        if (skuBase.skus && Array.isArray(skuBase.skus)) {
                            for (var k = 0; k < skuBase.skus.length; k++) {
                                var skuItem = skuBase.skus[k];
                                var propPath = (skuItem.propPath || '').trim();
                                var parts = [];
                                if (propPath) {
                                    var pairs = propPath.split(';');
                                    for (var pi = 0; pi < pairs.length; pi++) {
                                        var pair = pairs[pi].trim();
                                        if (valMap[pair]) {
                                            parts.push(valMap[pair].name);
                                        }
                                    }
                                }
                                if (parts.length > 0) {
                                    var comboPrice = '';
                                    if (skuItem.price) {
                                        if (typeof skuItem.price === 'string') comboPrice = skuItem.price;
                                        else if (skuItem.price.salePrice && skuItem.price.salePrice.text) comboPrice = skuItem.price.salePrice.text;
                                        else if (skuItem.price.currentPrice) comboPrice = skuItem.price.currentPrice;
                                    }
                                    var inStock = true;
                                    if (typeof skuItem.stock !== 'undefined' && skuItem.stock === 0) inStock = false;
                                    if (typeof skuItem.quantity !== 'undefined' && skuItem.quantity === 0) inStock = false;

                                    combinations.push({
                                        skuId: String(skuItem.skuId || skuItem.innerSkuId || k),
                                        name: parts.join(' / '),
                                        parts: parts,
                                        price: comboPrice,
                                        inStock: inStock
                                    });
                                }
                            }
                        }
                    }
                } catch(e) {}

                // B. Trích xuất dự phòng trực tiếp từ các khối DOM của từng lớp (nếu JS chưa có)
                if (layers.length === 0) {
                    var candidateBlocks = document.querySelectorAll(
                        '.sku-prop, [class*="sku-prop"], [class*="skuProp"], [class*="sku-section"], .pdp-mod-product-info-section-sku > div, .pdp-block__sku'
                    );

                    // Lọc Top-level blocks: Loại bỏ phần tử con bị lồng bên trong block khác và popup/dialog
                    var topBlocks = [];
                    for (var i = 0; i < candidateBlocks.length; i++) {
                        var b = candidateBlocks[i];
                        var cls = (b.className || '').toString();
                        if (cls.indexOf('sku-prop-content-item') !== -1 || cls.indexOf('sku-prop-title') !== -1) {
                            continue;
                        }
                        if (b.closest && b.closest('.next-dialog, .pdp-drawer, .sku-drawer, [style*="display: none"], [style*="display:none"], [hidden]')) {
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
                        var titleEl = block.querySelector('.sku-prop-title, [class*="prop-title"], .pdp-mod-product-info-section-title, .section-title, h3');
                        var groupName = '';
                        if (titleEl) {
                            var fullT = titleEl.innerText || '';
                            var subVal = titleEl.querySelector('.sku-name, [class*="selected"], span:not(:first-child)');
                            if (subVal) fullT = fullT.replace(subVal.innerText, '');
                            groupName = fullT.split(/[:：]/)[0].trim();
                        }

                        // Các tùy chọn trong lớp
                        var items = block.querySelectorAll(
                            '[class*="sku-variable"], [class*="sku-item"], [class*="skuItem"], [class*="sku_item"], [class*="radio"], [class*="swatch"], .sku-prop-content-item, .sku-name'
                        );
                        var options = [];
                        var seenOpts = {};
                        for (var it = 0; it < items.length; it++) {
                            var itemEl = items[it];
                            var optName = itemEl.getAttribute('title') || itemEl.getAttribute('data-text') || itemEl.getAttribute('data-sku-name') || '';
                            if (!optName) {
                                var imgEl = itemEl.querySelector('img');
                                if (imgEl) optName = imgEl.getAttribute('alt') || imgEl.getAttribute('title') || '';
                            }
                            if (!optName) {
                                optName = (itemEl.innerText || '').split(/[\r\n]+/)[0];
                            }
                            optName = optName.trim();
                            var optLower = optName.toLowerCase();

                            if (!optName || seenOpts[optLower] ||
                                optLower === 'quantity' || optLower === 'số lượng' ||
                                optLower === 'bảng kích cỡ' || optLower === 'size chart' || optLower === 'hướng dẫn') {
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
                res.combinations = combinations;

                // 6. Kiểm tra nút Thêm vào giỏ
                var addBtn = document.querySelector('button.add-to-cart-buy-now-btn, button.pdp-button_theme_orange, .pdp-button-add-to-cart');
                if (!addBtn) {
                    res.isOutOfStock = true;
                }
            } catch(e) {
                console.error("Lỗi trích xuất JS:", e);
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
        raw_combos = result.get("combinations") or []
        if not raw_combos and layers:
            combinations = generate_combinations(layers)
        else:
            combinations = raw_combos

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
            "combinations": combinations,
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
            for target in targets:
                driver.execute_script(r'''
                    var wanted = arguments[0].trim().toLowerCase();
                    var candidates = document.querySelectorAll(
                        '[class*="sku-variable"], [class*="sku-item"], [class*="skuItem"], [class*="sku_item"], [class*="radio"], [class*="swatch"], .sku-prop-content-item, .sku-name, [title]'
                    );
                    for (var i = 0; i < candidates.length; i++) {
                        var el = candidates[i];
                        if (el.offsetParent === null) continue;

                        var txt = el.getAttribute('title') || el.getAttribute('data-text') || el.getAttribute('data-sku-name') || '';
                        if (!txt) {
                            var img = el.querySelector('img');
                            if (img) txt = img.getAttribute('alt') || img.getAttribute('title') || '';
                        }
                        if (!txt) {
                            txt = (el.innerText || '').split(/[\r\n]+/)[0];
                        }
                        txt = txt.trim().toLowerCase();

                        if (txt === wanted || (txt.length >= 2 && wanted.indexOf(txt) === 0) || (wanted.length >= 2 && txt.indexOf(wanted) === 0)) {
                            var clickTarget = el.closest('button, [role="radio"], [role="button"], li, div[class*="sku-variable"], [class*="item"]') || el;
                            try {
                                clickTarget.scrollIntoView({ block: 'center', inline: 'center' });
                            } catch(e) {}
                            clickTarget.click();
                            try {
                                clickTarget.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                            } catch(e) {}
                            return true;
                        }
                    }
                    return false;
                ''', target)
                time.sleep(0.3)

        # 2. Click nút 'Thêm vào giỏ hàng'
        add_result = driver.execute_script(r'''
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
            success_check = driver.execute_script(r'''
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
