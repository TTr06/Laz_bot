import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from anti_detect import create_stealth_driver, COOKIES_FILE

def test_cart_navigation():
    if not os.path.exists(COOKIES_FILE):
        print("Cookies file not found!")
        return

    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        raw_cookies = json.load(f)

    print(f"Loaded {len(raw_cookies)} cookies from file.")

    driver = create_stealth_driver(headless=True)
    try:
        # Navigate to base domain first
        driver.get("https://www.lazada.vn")
        time.sleep(2)

        # Use CDP Network.setCookies to inject all cookies accurately
        cdp_cookies = []
        for c in raw_cookies:
            cookie_dict = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".lazada.vn"),
                "path": c.get("path", "/"),
            }
            if "secure" in c:
                cookie_dict["secure"] = c["secure"]
            if "httpOnly" in c:
                cookie_dict["httpOnly"] = c["httpOnly"]
            cdp_cookies.append(cookie_dict)

        driver.execute_cdp_cmd("Network.setCookies", {"cookies": cdp_cookies})
        print("Injected cookies via CDP.")

        # Now go directly to cart
        print("Navigating to https://cart.lazada.vn/cart...")
        driver.get("https://cart.lazada.vn/cart")
        time.sleep(5)

        print("Current URL:", driver.current_url)
        print("Page Title:", driver.title)

        # Save screenshot and html
        driver.save_screenshot("cart_test.png")
        with open("cart_test.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)

        print("Saved screenshot to cart_test.png and html to cart_test.html")

        # Check for elements in cart
        text = driver.page_source
        if "login" in driver.current_url or "member.lazada.vn" in driver.current_url:
            print("Status: REDIRECTED TO LOGIN")
        elif "cart" in driver.current_url:
            print("Status: ON CART PAGE!")
        else:
            print(f"Status: Landed on {driver.current_url}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    test_cart_navigation()
