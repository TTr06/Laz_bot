"""
Cookie Manager for Lazada
Hỗ trợ nạp cookie từ:
1. File JSON (Cookie-Editor, EditThisCookie, Selenium dump)
2. Chuỗi JSON dán trực tiếp
3. Chuỗi Header Cookie (F12 Network: `name1=val1; name2=val2`)
4. File cookie.json hoặc cookie.txt
"""

import json
import os
import re
import sys
from typing import List, Dict, Any, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(BASE_DIR, "lazada_cookies.json")
COOKIE_JSON_FILE = os.path.join(BASE_DIR, "cookie.json")
COOKIE_TXT_FILE = os.path.join(BASE_DIR, "cookie.txt")


def normalize_cookie_text(text: str) -> str:
    """Chuẩn hóa ký tự nháy kép thông minh và ký tự đặc biệt khi copy từ điện thoại/Telegram"""
    if not text:
        return ""
    return (
        text.replace('“', '"')
        .replace('”', '"')
        .replace('„', '"')
        .replace('″', '"')
        .replace('‘', "'")
        .replace('’', "'")
        .replace('`', "'")
    )


def extract_json_candidate(text: str) -> Any:
    """Trích xuất và parse JSON từ text bất kể có văn bản thừa xung quanh hay không"""
    clean_text = normalize_cookie_text(text.strip())

    # 1. Thử parse trực tiếp
    try:
        return json.loads(clean_text)
    except Exception:
        pass

    # 2. Tìm khối markdown ```json ... ``` hoặc ``` ... ```
    blocks = re.findall(r'```(?:json)?\s*([\s\S]*?)\s*```', clean_text, re.IGNORECASE)
    for block in blocks:
        try:
            return json.loads(block.strip())
        except Exception:
            pass

    # 3. Tìm mảng [ ... ] lớn nhất
    start_arr = clean_text.find('[')
    end_arr = clean_text.rfind(']')
    if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
        candidate = clean_text[start_arr:end_arr+1].strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # 4. Tìm object { ... } lớn nhất
    start_obj = clean_text.find('{')
    end_obj = clean_text.rfind('}')
    if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
        candidate = clean_text[start_obj:end_obj+1].strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return None


def parse_json_cookies(data: Any) -> List[Dict[str, Any]]:
    """
    Xử lý các dạng JSON cookie phổ biến (Cookie-Editor, EditThisCookie, key-value dict)
    """
    cookies = []

    # Dạng { "cookies": [...] }
    if isinstance(data, dict):
        if "cookies" in data and isinstance(data["cookies"], list):
            data = data["cookies"]
        else:
            # Dạng key-value dict: { "lzd_sid": "123", "t_uid": "456" }
            for k, v in data.items():
                if isinstance(v, (str, int, float)):
                    cookies.append({
                        "name": str(k),
                        "value": str(v),
                        "domain": ".lazada.vn",
                        "path": "/",
                        "secure": True,
                        "httpOnly": False
                    })
            return cookies

    # Dạng mảng danh sách [ { "name": ..., "value": ... }, ... ]
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if not name or value is None:
                continue

            domain = item.get("domain", ".lazada.vn")
            # Chuẩn hóa domain Lazada
            if not domain.startswith(".") and not domain.startswith("lazada"):
                domain = ".lazada.vn"

            cookie_dict = {
                "name": str(name),
                "value": str(value),
                "domain": domain,
                "path": item.get("path", "/"),
                "secure": bool(item.get("secure", True)),
                "httpOnly": bool(item.get("httpOnly", False))
            }
            cookies.append(cookie_dict)

    return cookies


def parse_raw_cookie_string(raw_cookie: str, default_domain: str = ".lazada.vn") -> List[Dict[str, Any]]:
    """
    Chuyển chuỗi Cookie dạng 'name1=val1; name2=val2' thành list dict cookie
    """
    cookies = []
    lines = [line.strip() for line in raw_cookie.splitlines() if not line.strip().startswith('#')]
    raw_cookie = " ".join(lines)
    raw_cookie = re.sub(r'^[Cc]ookie:\s*', '', raw_cookie.strip())

    parts = raw_cookie.split(';')
    for part in parts:
        part = part.strip()
        if not part or '=' not in part:
            continue
        key, val = part.split('=', 1)
        key = key.strip()
        val = val.strip()
        if key and not key.startswith('#'):
            cookies.append({
                "name": key,
                "value": val,
                "domain": default_domain,
                "path": "/",
                "secure": True,
                "httpOnly": False
            })
    return cookies


def parse_cookie_input(content: str) -> List[Dict[str, Any]]:
    """
    Tự động nhận diện định dạng (JSON hoặc raw text) và parse ra danh sách cookie
    """
    if not content:
        return []

    # 1. Trích xuất JSON (hỗ trợ cả khi có văn bản thừa hoặc dán qua Telegram)
    json_data = extract_json_candidate(content)
    if json_data:
        cookies = parse_json_cookies(json_data)
        if cookies:
            return cookies

    # 2. Parse theo chuỗi raw header
    return parse_raw_cookie_string(content)


def save_cookies_list(cookies: List[Dict[str, Any]]) -> int:
    """Lưu cookies vào lazada_cookies.json và đồng bộ cả cookie.json"""
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)
    try:
        with open(COOKIE_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    return len(cookies)


def load_saved_cookies() -> List[Dict[str, Any]]:
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def import_from_json_file(file_path: str = COOKIE_JSON_FILE) -> Tuple[bool, str]:
    """Import cookie từ file JSON"""
    if not os.path.exists(file_path):
        return False, f"Không tìm thấy file {file_path}"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except Exception as e:
        return False, f"Không đọc được file {file_path}: {e}"

    if not content:
        return False, f"File {file_path} đang rỗng."

    cookies = parse_cookie_input(content)
    if not cookies:
        return False, "Không nhận diện được cookie hợp lệ trong file JSON."

    count = save_cookies_list(cookies)
    return True, f"Đã nạp thành công {count} cookies từ {os.path.basename(file_path)}"


def prompt_interactive_cookie() -> bool:
    """
    Hiển thị tùy chọn nạp cookie cho người dùng ở terminal console (đặc biệt hữu ích trên Termux)
    trước khi bot bắt đầu chạy.
    Trả về True nếu có nạp cookie mới, False nếu bỏ qua.
    """
    if not sys.stdin.isatty():
        return False

    print("\n" + "=" * 60)
    print("🍪 [Termux / Console] TÙY CHỌN NẠP COOKIE LAZADA KHỞI ĐỘNG")
    print("=" * 60)
    print(" [1] Dán chuỗi JSON Cookie trực tiếp (1 dòng hoặc nhiều dòng)")
    print(" [2] Nạp từ file cookie.json (hoặc đường dẫn tùy ý)")
    print(" [Enter] Bỏ qua và dùng Cookie hiện tại để khởi động bot ngay")
    print("-" * 60)

    try:
        choice = input("👉 Lựa chọn của bạn [1/2 hoặc nhấn Enter]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[+] Đang tiếp tục khởi động bot...")
        return False

    if choice == "1":
        print("\n📋 Hãy DÁN chuỗi JSON Cookie vào dưới đây.")
        print("💡 Gõ 'done' hoặc 'xong' trên một dòng mới (hoặc nhấn Enter 2 lần) khi dán xong:")
        lines = []
        try:
            while True:
                line = input()
                line_lower = line.strip().lower()
                if line_lower in ("xong", "done", "q", "exit"):
                    break
                if not line.strip():
                    if lines:
                        candidate = "\n".join(lines)
                        if parse_cookie_input(candidate):
                            break
                    else:
                        break
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            pass

        content = "\n".join(lines).strip()
        if content:
            cookies = parse_cookie_input(content)
            if cookies:
                count = save_cookies_list(cookies)
                print(f"✅ Đã nạp thành công {count} cookies vào lazada_cookies.json & cookie.json!\n")
                return True
            else:
                print("❌ Không nhận diện được cookie hợp lệ từ nội dung dán. Đang giữ cookie cũ.\n")
        else:
            print("⚠️ Không có nội dung nào được nhập. Tiếp tục với cookie cũ.\n")

    elif choice == "2":
        try:
            path_input = input("📂 Nhập đường dẫn file (mặc định: cookie.json): ").strip()
        except (EOFError, KeyboardInterrupt):
            path_input = ""
        file_path = path_input if path_input else COOKIE_JSON_FILE
        success, msg = import_from_json_file(file_path)
        print(f"[{'OK' if success else '!'}] {msg}\n")
        return success

    return False



if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    target_file = sys.argv[1] if len(sys.argv) > 1 else COOKIE_JSON_FILE
    success, msg = import_from_json_file(target_file)
    print(f"[{'OK' if success else '!'}] {msg}")
