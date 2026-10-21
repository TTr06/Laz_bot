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

# CDP stealth
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
    """
})

try:
    print("[*] Navigating to lazada.vn to inject cookies...")
    driver.get("https://www.lazada.vn")
    time.sleep(2)

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
    print("[*] Injected cookies via CDP.")

    print("[*] Navigating to cart: https://cart.lazada.vn/cart...")
    driver.get("https://cart.lazada.vn/cart")
    time.sleep(4)

    print("Current URL:", driver.current_url)

    # Click Select All checkbox
    print("[*] Finding and clicking 'Select All' checkbox...")
    click_res = driver.execute_script("""
        var cb = document.querySelector('.list-header-checkbox input, .checkbox-wrap label, .checkbox-wrap input, .list-header-checkbox');
        if (cb) {
            cb.click();
            return { found: true, tag: cb.tagName, class: cb.className };
        }
        return { found: false };
    """)
    print("Click result:", click_res)

    print("[*] Waiting 4 seconds for price recalculations...")
    time.sleep(4)

    # Check updated __initData__ or DOM elements
    init_data = driver.execute_script("return window.__initData__;")
    with open("cart_after_select_all.json", "w", encoding="utf-8") as f:
        json.dump(init_data, f, indent=2, ensure_ascii=False)
    print("[*] Saved updated initData to cart_after_select_all.json")

    # Read items and prices directly from DOM
    dom_summary = driver.execute_script("""
        var items = [];
        // DOM items
        var itemNodes = document.querySelectorAll('.cart-item, [data-spm=\"cart_item\"], .item-content, [class*=\"itemContainer\"]');
        itemNodes.forEach(function(node) {
            var titleEl = node.querySelector('a[class*=\"title\"], [class*=\"item-title\"], [class*=\"product-title\"]');
            var priceEl = node.querySelector('[class*=\"current-price\"], [class*=\"price\"], [class*=\"Price\"], span[class*=\"currency\"]');
            var cb = node.querySelector('input[type=\"checkbox\"], label[class*=\"checkbox\"]');
            if (titleEl) {
                items.push({
                    title: titleEl.innerText.trim(),
                    price: priceEl ? priceEl.innerText.trim() : 'N/A',
                    checked: cb ? (cb.checked || cb.getAttribute('aria-checked') === 'true' || cb.className.includes('checked')) : null
                });
            }
        });

        // Checkout / Total summary
        var totalEl = document.querySelector('.total-price, .order-summary-total, [class*=\"summary-total\"], [class*=\"totalPrice\"]');
        var totalText = totalEl ? totalEl.innerText.trim() : 'N/A';

        return { items: items, total: totalText };
    """)

    print(f"\n[OK] DOM extracted {len(dom_summary['items'])} items.")
    print(f"Total order price: {dom_summary['total']}")
    for i, it in enumerate(dom_summary['items'][:10], 1):
        print(f"  {i}. {it['title'][:50]} -> Price: {it['price']} (Checked: {it['checked']})")

finally:
    driver.quit()
    print("[*] Done.")
