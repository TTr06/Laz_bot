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
    content = content.strip()
    if not content:
        return []

    # 1. Thử parse dạng JSON trước
    try:
        parsed_json = json.loads(content)
        cookies = parse_json_cookies(parsed_json)
        if cookies:
            return cookies
    except Exception:
        pass

    # 2. Thử parse theo regex JSON nếu có bao quanh bởi markdown code block
    json_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if json_block:
        try:
            parsed_json = json.loads(json_block.group(1).strip())
            cookies = parse_json_cookies(parsed_json)
            if cookies:
                return cookies
        except Exception:
            pass

    # 3. Parse theo chuỗi raw header
    return parse_raw_cookie_string(content)


def save_cookies_list(cookies: List[Dict[str, Any]]) -> int:
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)
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
    return True, f"Đã nạp thành công {count} cookies từ {os.path.basename(file_path)} vào lazada_cookies.json"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    target_file = sys.argv[1] if len(sys.argv) > 1 else COOKIE_JSON_FILE
    success, msg = import_from_json_file(target_file)
    print(f"[{'OK' if success else '!'}] {msg}")
