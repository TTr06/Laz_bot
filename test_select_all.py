import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from anti_detect import (
    create_stealth_driver,
    load_cookies,
    save_cookies,
    random_delay,
    safe_quit,
    COOKIES_FILE,
)

def test_select_all():
    print("[*] Launching headless browser...")
    driver = create_stealth_driver(headless=True)
    try:
        print("[*] Loading cookies...")
        load_cookies(driver)

        print("[*] Navigating to cart...")
        driver.get("https://cart.lazada.vn/cart")
        time.sleep(5)

        print("Current URL:", driver.current_url)

        # Find the Select All checkbox
        print("[*] Finding 'Select all' checkbox...")
        select_all_btn = None
        selectors = [
            ".list-header-checkbox",
            ".checkbox-wrap .next-checkbox",
            ".list-header .next-checkbox",
            "label.list-header-checkbox",
            ".checkbox-wrap label"
        ]
        for sel in selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                for e in elems:
                    if e.is_displayed():
                        select_all_btn = e
                        print(f"[OK] Found element with selector: {sel}")
                        break
                if select_all_btn:
                    break
            except Exception:
                continue

        if not select_all_btn:
            print("[!] Could not find displayed Select All checkbox by selector, trying JS click...")
            driver.execute_script("""
                var cb = document.querySelector('.list-header-checkbox, .checkbox-wrap label, .checkbox-wrap input');
                if (cb) { cb.click(); }
            """)
        else:
            print("[*] Clicking 'Select all' checkbox...")
            try:
                select_all_btn.click()
            except Exception as e:
                print(f"[!] Normal click failed ({e}), using JS click...")
                driver.execute_script("arguments[0].click();", select_all_btn)

        # Wait for Lazada to recalculate prices
        print("[*] Waiting 6 seconds for network recalculations...")
        time.sleep(6)

        # Check checkbox state
        cb_state = driver.execute_script("""
            var input = document.querySelector('.list-header-checkbox input, .checkbox-wrap input');
            var label = document.querySelector('.list-header-checkbox, .checkbox-wrap label');
            return {
                inputChecked: input ? input.checked : null,
                ariaChecked: input ? input.getAttribute('aria-checked') : null,
                labelClass: label ? label.className : null
            };
        """)
        print("Checkbox state after click:", cb_state)

        # Get updated initData
        new_init_data = driver.execute_script("return window.__initData__;")
        if new_init_data:
            with open("cart_selected_init_data.json", "w", encoding="utf-8") as f:
                json.dump(new_init_data, f, indent=2, ensure_ascii=False)
            print("[OK] Saved updated initData to cart_selected_init_data.json")

        # Save screenshot and html
        driver.save_screenshot("cart_selected.png")
        with open("cart_selected.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("[OK] Saved screenshot to cart_selected.png and HTML to cart_selected.html")

    finally:
        safe_quit(driver)

if __name__ == "__main__":
    test_select_all()
