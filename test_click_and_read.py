import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

driver_path = r'C:\Users\thinh\.wdm\drivers\chromedriver\win64\155.0.8059.84\chromedriver-win64\chromedriver.exe'
COOKIES_FILE = "lazada_cookies.json"

options = Options()
options.add_argument('--headless=new')
options.add_argument('--disable-gpu')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_experimental_option('excludeSwitches', ['enable-automation'])
options.add_experimental_option('useAutomationExtension', False)
options.add_argument(
    "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

service = Service(driver_path)
driver = webdriver.Chrome(service=service, options=options)

driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
    """
})

try:
    driver.get("https://www.lazada.vn")
    time.sleep(1.5)

    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    cdp_cookies = []
    for c in cookies:
        cdp_cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".lazada.vn"),
            "path": c.get("path", "/"),
            "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False)
        })
    driver.execute_cdp_cmd("Network.setCookies", {"cookies": cdp_cookies})

    driver.get("https://cart.lazada.vn/cart")
    time.sleep(4)

    # Click Select All
    print("[*] Triggering Select All click...")
    driver.execute_script("""
        var btn = document.querySelector('.list-header-checkbox input, .checkbox-wrap label, .list-header-checkbox');
        if (btn) btn.click();
    """)

    # Wait for summary to update
    for sec in range(1, 10):
        time.sleep(1)
        summary_text = driver.execute_script("""
            var el = document.querySelector('.checkout-summary, .summary-section');
            return el ? el.innerText : '';
        """)
        if '0 items' not in summary_text and summary_text:
            print(f"[OK] Summary updated after {sec}s!")
            break

    # Read updated checkout summary
    res = driver.execute_script("""
        var summaryEl = document.querySelector('.checkout-summary, .summary-section');
        var summaryText = summaryEl ? summaryEl.innerText : 'N/A';
        
        // Items from DOM
        var domItems = [];
        var rows = document.querySelectorAll('.cart-item, [data-spm=\"cart_item\"], .item-content');
        rows.forEach(function(row) {
            var titleEl = row.querySelector('a[class*=\"title\"], [class*=\"item-title\"], [class*=\"product-title\"]');
            var currentPriceEl = row.querySelector('.current-price, [class*=\"current-price\"], [class*=\"price\"]');
            var originPriceEl = row.querySelector('.origin-price, [class*=\"origin-price\"]');
            var checkboxEl = row.querySelector('input[type=\"checkbox\"], label[class*=\"checkbox\"]');
            
            if (titleEl) {
                domItems.push({
                    title: titleEl.innerText.trim(),
                    currentPrice: currentPriceEl ? currentPriceEl.innerText.trim() : 'N/A',
                    originPrice: originPriceEl ? originPriceEl.innerText.trim() : null,
                    isChecked: checkboxEl ? (checkboxEl.checked || checkboxEl.className.includes('checked') || checkboxEl.getAttribute('aria-checked') === 'true') : false
                });
            }
        });
        
        return { summary: summaryText, items: domItems };
    """)

    print("\n=== SUMMARY PHẦN TỔNG KẾT ===")
    print(res.get("summary"))

    print("\n=== CÁC SẢN PHẨM TRÊN GIAO DIỆN SAU KHI CHỌN ===")
    for i, it in enumerate(res.get("items", []), 1):
        print(f"{i}. {it['title'][:55]}")
        print(f"   Giá hiển thị: {it['currentPrice']} (Giá gốc: {it['originPrice']}) | Chọn: {it['isChecked']}")

finally:
    driver.quit()
