package com.lazbot.tracker

import android.annotation.SuppressLint
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONArray
import org.json.JSONObject
import kotlin.coroutines.resume

data class CartScanResult(
    val status: String, // "ok", "need_login", "empty", "error"
    val message: String,
    val totalPrice: String = "0₫",
    val skuCount: Int = 0,
    val itemsSummary: String = "",
    val durationSeconds: Double = 0.0
)

class LazadaTrackerEngine(private val context: Context) {

    private val mainHandler = Handler(Looper.getMainLooper())

    @SuppressLint("SetJavaScriptEnabled")
    suspend fun scanCart(cookieRaw: String): CartScanResult = suspendCancellableCoroutine { continuation ->
        mainHandler.post {
            val startTime = System.currentTimeMillis()
            var isFinished = false

            fun finish(result: CartScanResult, webView: WebView?) {
                if (!isFinished) {
                    isFinished = true
                    try {
                        webView?.stopLoading()
                        webView?.clearHistory()
                        webView?.destroy()
                    } catch (e: Exception) {
                        // ignore
                    }
                    if (continuation.isActive) {
                        continuation.resume(result)
                    }
                }
            }

            if (cookieRaw.isBlank()) {
                finish(
                    CartScanResult(
                        status = "need_login",
                        message = "Chưa có cookie. Vui lòng dán cookie Lazada vào app."
                    ),
                    null
                )
                return@post
            }

            // Thiết lập CookieManager
            val cookieManager = CookieManager.getInstance()
            cookieManager.setAcceptCookie(true)
            applyCookies(cookieManager, cookieRaw)

            val webView = WebView(context)
            val settings = webView.settings
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.cacheMode = WebSettings.LOAD_DEFAULT
            settings.userAgentString = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

            // Timeout watchdog (25 giây)
            val timeoutRunnable = Runnable {
                val elapsed = (System.currentTimeMillis() - startTime) / 1000.0
                finish(
                    CartScanResult(
                        status = "error",
                        message = "Quá thời gian tải giỏ hàng (25s)",
                        durationSeconds = elapsed
                    ),
                    webView
                )
            }
            mainHandler.postDelayed(timeoutRunnable, 25000)

            // Javascript Interface nhận kết quả từ WebView
            class CartJsInterface {
                @JavascriptInterface
                fun onCartExtracted(jsonStr: String) {
                    mainHandler.removeCallbacks(timeoutRunnable)
                    mainHandler.post {
                        val elapsed = (System.currentTimeMillis() - startTime) / 1000.0
                        try {
                            val json = JSONObject(jsonStr)
                            val status = json.optString("status", "error")
                            val total = json.optString("total", "0₫")
                            val skuCount = json.optInt("sku_count", 0)
                            val msg = json.optString("message", "")
                            val items = json.optString("items_summary", "")

                            finish(
                                CartScanResult(
                                    status = status,
                                    message = msg,
                                    totalPrice = total,
                                    skuCount = skuCount,
                                    itemsSummary = items,
                                    durationSeconds = elapsed
                                ),
                                webView
                            )
                        } catch (e: Exception) {
                            finish(
                                CartScanResult(
                                    status = "error",
                                    message = "Lỗi phân tích kết quả: ${e.message}",
                                    durationSeconds = elapsed
                                ),
                                webView
                            )
                        }
                    }
                }
            }

            webView.addJavascriptInterface(CartJsInterface(), "AndroidBridge")

            webView.webViewClient = object : WebViewClient() {
                override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                    if (request?.isForMainFrame == true) {
                        mainHandler.removeCallbacks(timeoutRunnable)
                        val elapsed = (System.currentTimeMillis() - startTime) / 1000.0
                        finish(
                            CartScanResult(
                                status = "error",
                                message = "Lỗi kết nối mạng: ${error?.description}",
                                durationSeconds = elapsed
                            ),
                            webView
                        )
                    }
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)

                    if (url?.contains("member/login") == true) {
                        mainHandler.removeCallbacks(timeoutRunnable)
                        val elapsed = (System.currentTimeMillis() - startTime) / 1000.0
                        finish(
                            CartScanResult(
                                status = "need_login",
                                message = "Cookie đã hết hạn! Vui lòng nạp lại cookie mới.",
                                durationSeconds = elapsed
                            ),
                            webView
                        )
                        return
                    }

                    // Tiêm script tối ưu: Click 'Chọn tất cả' và trích xuất Giá Cuối Cùng
                    injectCartScannerScript(webView)
                }
            }

            // Tải trang giỏ hàng Lazada
            webView.loadUrl("https://cart.lazada.vn/cart")

            continuation.invokeOnCancellation {
                mainHandler.removeCallbacks(timeoutRunnable)
                mainHandler.post {
                    try {
                        webView.stopLoading()
                        webView.destroy()
                    } catch (e: Exception) {
                        // ignore
                    }
                }
            }
        }
    }

    private fun injectCartScannerScript(webView: WebView) {
        val script = """
            (function() {
                var checkCount = 0;
                var maxChecks = 40; // 40 * 150ms = 6s

                var poller = setInterval(function() {
                    checkCount++;
                    
                    // 1. Kiểm tra giỏ hàng trống
                    if (document.querySelector('.cart-empty, .empty-cart, .cart-empty-text')) {
                        clearInterval(poller);
                        AndroidBridge.onCartExtracted(JSON.stringify({
                            status: "empty",
                            total: "0₫",
                            sku_count: 0,
                            message: "Giỏ hàng trống"
                        }));
                        return;
                    }

                    // 2. Tìm checkbox 'Chọn tất cả'
                    var selectAllCb = document.querySelector(
                        'input.next-checkbox-input[type="checkbox"], ' +
                        '.list-header-checkbox input, ' +
                        '.cart-select-all input, ' +
                        '.selectAll input'
                    );

                    if (selectAllCb && !selectAllCb.checked) {
                        selectAllCb.click();
                    }

                    // 3. Kiểm tra xem tóm tắt đơn hàng (Checkout Summary) hoặc initData đã sẵn sàng chưa
                    var summaryEl = document.querySelector('.checkout-summary, .cart-order-summary, .checkout-summary-row');
                    var initData = window.__initData__ && window.__initData__.module && window.__initData__.module.data;

                    if (summaryEl || initData || checkCount >= maxChecks) {
                        clearInterval(poller);
                        
                        // Đợi 400ms sau click để voucher cập nhật chính xác
                        setTimeout(function() {
                            var totalPrice = "0₫";
                            var skuCount = 0;
                            var itemsDesc = [];

                            // Đọc từ DOM checkout-summary
                            var totalValueEl = document.querySelector('.checkout-summary-value, .checkout-order-total-value, .current-price');
                            if (totalValueEl && totalValueEl.innerText.trim()) {
                                totalPrice = totalValueEl.innerText.trim();
                            }

                            // Đọc từ __initData__ nếu có
                            if (window.__initData__ && window.__initData__.module && window.__initData__.module.data) {
                                var data = window.__initData__.module.data;
                                if (data.checkoutSummary && data.checkoutSummary.total) {
                                    totalPrice = data.checkoutSummary.total;
                                }
                                if (data.items && Array.isArray(data.items)) {
                                    skuCount = data.items.length;
                                    data.items.slice(0, 5).forEach(function(item) {
                                        var title = item.title || item.itemName || "Sản phẩm";
                                        var p = item.price || item.itemPrice || "";
                                        itemsDesc.push("• " + title.substring(0, 30) + "...: " + p);
                                    });
                                }
                            }

                            if (skuCount === 0) {
                                var itemEls = document.querySelectorAll('.cart-item, .item-container, .shop-item');
                                skuCount = itemEls.length;
                            }

                            AndroidBridge.onCartExtracted(JSON.stringify({
                                status: "ok",
                                total: totalPrice,
                                sku_count: skuCount,
                                items_summary: itemsDesc.join("\n"),
                                message: "Đã đọc giỏ hàng thành công"
                            }));
                        }, 400);
                    }
                }, 150);
            })();
        """.trimIndent()

        webView.evaluateJavascript(script, null)
    }

    private fun applyCookies(cookieManager: CookieManager, raw: String) {
        val trimmed = raw.trim()
        if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
            // Định dạng JSON array (như export từ extension J2Team / Cookie-Editor)
            try {
                val array = JSONArray(trimmed)
                for (i in 0 until array.length()) {
                    val obj = array.getJSONObject(i)
                    val name = obj.optString("name")
                    val value = obj.optString("value")
                    val domain = obj.optString("domain", ".lazada.vn")
                    if (name.isNotEmpty()) {
                        val cookieStr = "$name=$value; domain=$domain; path=/"
                        cookieManager.setCookie("https://cart.lazada.vn", cookieStr)
                        cookieManager.setCookie("https://www.lazada.vn", cookieStr)
                    }
                }
                cookieManager.flush()
                return
            } catch (e: Exception) {
                // Fallback nếu không parse được JSON
            }
        }

        // Định dạng cookie string dạng name=value; name2=value2
        val pairs = trimmed.split(";")
        for (pair in pairs) {
            val parts = pair.trim().split("=", limit = 2)
            if (parts.size == 2) {
                val key = parts[0].trim()
                val value = parts[1].trim()
                if (key.isNotEmpty()) {
                    val cookieStr = "$key=$value; domain=.lazada.vn; path=/"
                    cookieManager.setCookie("https://cart.lazada.vn", cookieStr)
                    cookieManager.setCookie("https://www.lazada.vn", cookieStr)
                }
            }
        }
        cookieManager.flush()
    }
}
