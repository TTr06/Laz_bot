"""
Lazada Login Tool - Selenium
Mở trình duyệt để đăng nhập Lazada thủ công, lưu cookies để dùng lại.
"""

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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Đường dẫn lưu cookies
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "lazada_cookies.json")
LAZADA_URL = "https://www.lazada.vn"
LAZADA_LOGIN_URL = "https://member.lazada.vn/user/login"


def create_driver(headless: bool = False) -> webdriver.Chrome:
    """Tạo Chrome WebDriver"""
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # Dùng user-agent thật để tránh bị phát hiện bot
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    if headless:
        options.add_argument("--headless=new")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # Ẩn dấu hiệu automation
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        },
    )
    return driver


def save_cookies(driver: webdriver.Chrome) -> None:
    """Lưu cookies ra file JSON"""
    cookies = driver.get_cookies()
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)
    print(f"[OK] Da luu {len(cookies)} cookies vao {COOKIES_FILE}")


def load_cookies(driver: webdriver.Chrome) -> bool:
    """Load cookies từ file vào browser"""
    if not os.path.exists(COOKIES_FILE):
        print("[!] Chua co file cookies. Can dang nhap truoc.")
        return False

    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    # Phải mở trang trước rồi mới add cookies
    driver.get(LAZADA_URL)
    time.sleep(2)

    for cookie in cookies:
        # Xóa các field có thể gây lỗi
        cookie.pop("sameSite", None)
        cookie.pop("httpOnly", None)
        cookie.pop("expiry", None)
        try:
            driver.add_cookie(cookie)
        except Exception as e:
            pass  # Bỏ qua cookies domain khác

    print(f"[OK] Da load {len(cookies)} cookies.")
    return True


def check_login_status(driver: webdriver.Chrome) -> bool:
    """Kiểm tra đã đăng nhập chưa"""
    driver.get(LAZADA_URL)
    time.sleep(3)
    try:
        # Tìm element chỉ xuất hiện khi đã đăng nhập (avatar/tên user)
        driver.find_element(By.CSS_SELECTOR, ".my-account-name, .lzd-header-user, [data-apm='myacc']")
        return True
    except Exception:
        return False


def login_manual() -> None:
    """Mở trình duyệt để đăng nhập thủ công, sau đó lưu cookies"""
    print("=" * 50)
    print("  LAZADA LOGIN TOOL")
    print("=" * 50)
    print()

    driver = create_driver()

    try:
        # Kiểm tra cookies cũ
        if os.path.exists(COOKIES_FILE):
            print("[*] Tim thay cookies cu, dang thu load...")
            load_cookies(driver)
            driver.refresh()
            time.sleep(3)

            if check_login_status(driver):
                print("[OK] Da dang nhap thanh cong bang cookies cu!")
                print("[*] Trinh duyet se mo trong 30 giay de ban kiem tra...")
                time.sleep(30)
                return
            else:
                print("[!] Cookies het han. Can dang nhap lai.")

        # Mở trang đăng nhập
        print("[*] Dang mo trang dang nhap Lazada...")
        driver.get(LAZADA_LOGIN_URL)
        print()
        print(">>> HAY DANG NHAP TREN TRINH DUYET <<<")
        print(">>> Sau khi dang nhap xong, quay lai day nhan ENTER <<<")
        print()

        # Chờ user đăng nhập - kiểm tra mỗi 3 giây, tối đa 5 phút
        timeout = 300  # 5 phút
        start = time.time()
        logged_in = False

        while time.time() - start < timeout:
            try:
                current_url = driver.current_url
                # Nếu đã redirect về trang chủ = đã đăng nhập
                if "lazada.vn" in current_url and "login" not in current_url and "member" not in current_url:
                    logged_in = True
                    break
            except Exception:
                pass
            time.sleep(3)

        if not logged_in:
            # Thử kiểm tra lần cuối
            try:
                current_url = driver.current_url
                if "login" not in current_url:
                    logged_in = True
            except Exception:
                pass

        if logged_in:
            print("[OK] Phat hien da dang nhap thanh cong!")
        else:
            print("[?] Khong chac da dang nhap. Van se thu luu cookies...")

        # Đợi thêm để trang load hết cookies
        time.sleep(3)

        # Lưu cookies
        save_cookies(driver)

        # Xác nhận
        print()
        print("[OK] HOAN TAT!")
        print(f"[*] Cookies da luu tai: {COOKIES_FILE}")
        print("[*] Lan sau chay tool se tu dong dang nhap bang cookies.")
        print()
        print("[*] Trinh duyet se dong sau 10 giay...")
        time.sleep(10)

    except KeyboardInterrupt:
        print("\n[!] Da huy boi nguoi dung.")
    except Exception as e:
        print(f"[!] Loi: {e}")
    finally:
        driver.quit()
        print("[*] Da dong trinh duyet.")


def login_with_cookies() -> webdriver.Chrome | None:
    """Đăng nhập bằng cookies đã lưu, trả về driver nếu thành công"""
    if not os.path.exists(COOKIES_FILE):
        print("[!] Chua co cookies. Hay chay login_manual() truoc.")
        return None

    driver = create_driver()
    load_cookies(driver)
    driver.refresh()
    time.sleep(3)

    if check_login_status(driver):
        print("[OK] Dang nhap thanh cong bang cookies!")
        return driver
    else:
        print("[!] Cookies het han. Hay chay login_manual() lai.")
        driver.quit()
        return None


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Lazada Login Tool")
    parser.add_argument(
        "--mode",
        choices=["login", "check", "clear"],
        default="login",
        help="login: Dang nhap thu cong | check: Kiem tra cookies | clear: Xoa cookies",
    )
    args = parser.parse_args()

    if args.mode == "login":
        login_manual()
    elif args.mode == "check":
        driver = login_with_cookies()
        if driver:
            print("[*] Trinh duyet se dong sau 15 giay...")
            time.sleep(15)
            driver.quit()
    elif args.mode == "clear":
        if os.path.exists(COOKIES_FILE):
            os.remove(COOKIES_FILE)
            print("[OK] Da xoa cookies.")
        else:
            print("[!] Khong co cookies de xoa.")
