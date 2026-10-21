"""
Anti-detect Browser Module
Cấu hình trình duyệt chống phát hiện bot.
Sử dụng local ChromeDriver ổn định, tốc độ khởi động nhanh (< 1 giây).
"""

import json
import os
import random
import re
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(BASE_DIR, "lazada_cookies.json")

# Danh sách user-agent thực tế
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]


def find_chromedriver_path() -> str:
    """Tìm đường dẫn local ChromeDriver đã có sẵn trên máy"""
    candidates = [
        r"C:\Users\thinh\.wdm\drivers\chromedriver\win64\155.0.8059.84\chromedriver-win64\chromedriver.exe",
        r"C:\Program Files\Google\Chrome\Application\chromedriver.exe"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    # Tìm đệ quy trong thư mục .wdm
    wdm_root = os.path.expanduser(r"~/.wdm/drivers/chromedriver")
    if os.path.exists(wdm_root):
        for root, dirs, files in os.walk(wdm_root):
            if "chromedriver.exe" in files:
                return os.path.join(root, "chromedriver.exe")

    return "chromedriver"


def random_delay(min_sec: float = 1.0, max_sec: float = 2.5) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def safe_quit(driver) -> None:
    if not driver:
        return
    try:
        driver.quit()
    except Exception:
        pass


def create_stealth_driver(headless: bool = True) -> webdriver.Chrome:
    """Khởi tạo trình duyệt với cờ stealth và CDP bypass"""
    options = Options()
    options.page_load_strategy = 'eager'  # Tải nhanh DOMContentLoaded, không chờ tracker/ads chậm
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")

    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--lang=vi-VN,vi,en-US,en")

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    ua = random.choice(USER_AGENTS)
    options.add_argument(f"user-agent={ua}")

    driver_path = find_chromedriver_path()
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(20)

    # CDP evasions
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [
                { name: 'Chrome PDF Viewer' },
                { name: 'Native Client' }
            ]});
            Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
        """
    })

    return driver


def load_cookies(driver) -> bool:
    """Nạp cookie qua giao thức CDP áp dụng cho toàn bộ domain Lazada"""
    if not os.path.exists(COOKIES_FILE):
        return False

    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
    except Exception:
        return False

    if not cookies:
        return False

    # Mở domain cơ sở
    driver.get("https://www.lazada.vn")
    time.sleep(1.5)

    cdp_cookies = []
    for c in cookies:
        domain = c.get("domain", ".lazada.vn")
        cdp_cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path", "/"),
            "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False)
        })

    try:
        driver.execute_cdp_cmd("Network.setCookies", {"cookies": cdp_cookies})
        return True
    except Exception as e:
        print(f"[!] Lỗi nạp CDP cookies: {e}")
        return False


def save_cookies(driver) -> int:
    """Lưu và đồng bộ cookie mới nhưng bảo vệ các auth tokens quan trọng không bị ghi đè bởi guest session"""
    try:
        new_cookies = driver.get_cookies()
        if not new_cookies:
            return 0
            
        existing = {}
        if os.path.exists(COOKIES_FILE):
            try:
                with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                    for c in json.load(f):
                        existing[c["name"]] = c
            except Exception:
                pass

        # Các cookie xác thực tài khoản cốt lõi cần bảo toàn
        critical_auth = {"lzd_sid", "t_sid", "t_uid", "lzd_uid", "sgcookie", "epssw", "_tb_token_"}
        for nc in new_cookies:
            name = nc.get("name")
            if name in critical_auth:
                # Nếu đã có token xác thực thì giữ nguyên, tránh bị session guest ghi đè
                if name not in existing:
                    existing[name] = nc
            else:
                existing[name] = nc

        merged = list(existing.values())
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        return len(merged)
    except Exception:
        return 0
