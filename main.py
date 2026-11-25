"""
================================================================================
 LAZADA TRACKER & FATHER BOT - UNIFIED MAIN RUNNER (main.py)
================================================================================
 Kiến trúc hợp nhất:
 1. Nền tảng hướng đối tượng kế thừa chuẩn từ CmdLineInterface (theo mẫu cli.h).
 2. Chạy ngầm đa luồng (Background Thread):
    - Father Bot Telegram (python-telegram-bot v20+)
    - Auto Scheduler tự động quét giỏ hàng theo chu kỳ 1p/lần
 3. Giao diện dòng lệnh tương tác trên Host (Interactive REPL Host CLI):
    - In log ngầm (tiến trình quét, biến động giá, thông báo bot) Ở PHÍA TRÊN.
    - Con trỏ nhập lệnh (LazBot> ) luôn được ghim ở DÒNG DƯỚI CÙNG.
    - Không làm gián đoạn hay vỡ các ký tự người dùng đang gõ dở.
================================================================================
"""

import os
import sys
import time
import shlex
import logging
import threading
import asyncio
from datetime import datetime
from typing import Optional, List, Tuple

# Bật mã thoát ANSI trên Windows 10/11
os.system("")

# Thiết lập bảng mã UTF-8 cho toàn bộ console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv()

import database
import cookie_manager
from bot import create_bot_app
from database import get_subscribers, is_auto_track_enabled
from dashboard import print_cli, dashboard
from web_server import web_server

# Thiết lập log mức INFO
logging.basicConfig(
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("main")


# ==============================================================================
# 1. BỘ ĐỆM XUẤT NHẬP DÒNG LỆNH (STREAM INTERCEPTOR CHO FALLBACK / NON-TTY)
# ==============================================================================
class FallbackStdoutProxy:
    """
    Bộ bọc stdout/stderr an toàn đa luồng cho các môi trường không có console screen buffer:
    - Khi có log từ luồng ngầm đẩy ra lúc đang đợi người dùng gõ lệnh,
      hệ thống dùng mã ANSI \\r\\033[2K để xóa dòng prompt hiện tại,
      in dòng log hoàn chỉnh, rồi vẽ lại chuỗi prompt ở dòng tiếp theo.
    """
    def __init__(self, original_stream, get_prompt_func, is_waiting_func):
        self.original_stream = original_stream
        self.get_prompt = get_prompt_func
        self.is_waiting = is_waiting_func
        self.lock = threading.Lock()

    def write(self, s: str):
        with self.lock:
            if not s:
                return
            if self.is_waiting():
                # Xóa dòng đang nhập dở, in log, rồi in lại prompt
                try:
                    self.original_stream.write("\r\033[2K")
                except Exception:
                    self.original_stream.write("\r")
                self.original_stream.write(s)
                if not s.endswith("\n"):
                    self.original_stream.write("\n")
                prompt = self.get_prompt()
                self.original_stream.write(prompt)
                self.original_stream.flush()
            else:
                self.original_stream.write(s)
                self.original_stream.flush()

    def flush(self):
        with self.lock:
            self.original_stream.flush()

    def fileno(self):
        return self.original_stream.fileno()

    def isatty(self):
        return self.original_stream.isatty()


# ==============================================================================
# 2. LỚP CƠ SỞ GIAO DIỆN DÒNG LỆNH (CmdLineInterface - TƯƠNG THÍCH CHUẨN cli.h)
# ==============================================================================
class CmdLineInterface:
    """
    Lớp cơ sở giao diện dòng lệnh kế thừa mẫu OOP từ cli.h
    """
    def __init__(self, prompt: str = "LazBot> "):
        self.cmd_prompt = prompt
        self.b_running = True
        self.cmd_do_func = {}
        self.cmd_name_list = []
        self.cmd_default_id = None
        self.is_waiting_input = False

    def set_cmd_prompt(self, prompt: str):
        self.cmd_prompt = prompt

    def clear_screen(self):
        os.system("cls" if os.name == "nt" else "clear")

    def show_cmd_prompt(self):
        sys.stdout.write(self.cmd_prompt)
        sys.stdout.flush()

    def add_cmd(self, name: str, func):
        name_lower = name.lower()
        self.cmd_do_func[name_lower] = func
        if name_lower not in self.cmd_name_list:
            self.cmd_name_list.append(name_lower)

    def init_cmd(self):
        """Ghi đè trong lớp kế thừa để đăng ký bảng lệnh"""
        pass

    def init_console(self):
        """Ghi đè trong lớp kế thừa để khởi tạo console / in banner"""
        pass

    def parse_cmd(self, line: str) -> Tuple[str, List[str]]:
        line = line.strip()
        if not line:
            return "", []
        try:
            tokens = shlex.split(line)
        except ValueError:
            tokens = line.split()
        if not tokens:
            return "", []
        return tokens[0].lower(), tokens

    def do_unknown(self):
        print("[!] Lệnh không hợp lệ. Gõ 'help' để xem danh sách các lệnh hỗ trợ.")

    def do_quit(self):
        self.b_running = False

    def do_cmd(self, name: str, cmd_argv: List[str], cmd_argc: int):
        func = self.cmd_do_func.get(name.lower())
        if func:
            func(cmd_argv, cmd_argc)
        else:
            self.do_unknown()

    def read_cmd(self) -> str:
        """Đọc dòng lệnh từ người dùng"""
        try:
            self.is_waiting_input = True
            return input()
        except (EOFError, KeyboardInterrupt):
            return "quit"
        finally:
            self.is_waiting_input = False

    def run(self, init_argv: Optional[List[str]] = None):
        self.init_console()
        self.init_cmd()

        if init_argv and len(init_argv) > 1:
            first_cmd = init_argv[1].lower()
            if first_cmd in ("quit", "exit", "q"):
                self.do_quit()
                return
            if first_cmd in self.cmd_do_func:
                self.do_cmd(first_cmd, init_argv[1:], len(init_argv[1:]))
            else:
                self.do_unknown()
            return

        self.b_running = True
        while self.b_running:
            self.show_cmd_prompt()
            line = self.read_cmd()
            name, argv = self.parse_cmd(line)
            if not name:
                continue
            if name in ("quit", "exit", "q"):
                self.do_quit()
                break
            if name in self.cmd_do_func:
                self.do_cmd(name, argv, len(argv))
            else:
                self.do_unknown()


# ==============================================================================
# 3. LỚP ĐIỀU HÀNH CHÍNH HỢP NHẤT (LazBotMainCLI)
# ==============================================================================
class LazBotMainCLI(CmdLineInterface):
    """
    Lớp điều khiển hợp nhất:
    - Kế thừa trực tiếp từ CmdLineInterface
    - Quản lý luồng chạy ngầm của Telegram Bot + Scheduler
    - Sử dụng prompt_toolkit.patch_stdout để các dòng log ngầm đẩy lên trên,
      giữ nguyên vẹn dòng lệnh đang gõ ở dưới đáy màn hình.
    """
    def __init__(self, prompt: str = "LazBot> "):
        super().__init__(prompt)
        self.bot_thread: Optional[threading.Thread] = None
        self.bot_loop: Optional[asyncio.AbstractEventLoop] = None
        self.bot_app = None
        self.bot_is_running = False
        self.session = None
        self._init_prompt_session()
        self.init_cmd()

    def _init_prompt_session(self):
        """Khởi tạo prompt_toolkit session nếu console hỗ trợ"""
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import InMemoryHistory
            from prompt_toolkit.output.defaults import create_output
            # Kiểm tra xem có lấy được console screen buffer không
            out = create_output()
            self.session = PromptSession(history=InMemoryHistory(), output=out)
        except Exception:
            self.session = None

    def init_console(self):
        # Đảm bảo CSDL được khởi tạo bảng & chỉ mục
        database.init_db()
        self.print_banner()

    def init_cmd(self):
        # Đăng ký các chức năng CLI vào bảng lệnh
        self.add_cmd("help", self.cmd_help)
        self.add_cmd("prices", self.cmd_prices)
        self.add_cmd("list", self.cmd_prices)
        self.add_cmd("targets", self.cmd_targets)
        self.add_cmd("target", self.cmd_targets)
        self.add_cmd("setprice", self.cmd_setprice)
        self.add_cmd("delprice", self.cmd_delprice)
        self.add_cmd("cart", self.cmd_cart)
        self.add_cmd("scan", self.cmd_cart)
        self.add_cmd("track", self.cmd_track)
        self.add_cmd("cookie", self.cmd_cookie)
        self.add_cmd("bot", self.cmd_bot)
        self.add_cmd("web", self.cmd_web)
        self.add_cmd("db", self.cmd_db)
        self.add_cmd("clear", self.cmd_clear)
        self.add_cmd("cls", self.cmd_clear)

    def print_banner(self):
        print("=" * 76)
        print("          LAZADA TRACKER & FATHER BOT - UNIFIED HOST SYSTEM")
        print("    [Background: Bot Telegram & Auto Scheduler | Foreground: Host CLI]")
        print("=" * 76)
        print(" • Log hoạt động và biến động giá sẽ tự động cuộn ở PHÍA TRÊN.")
        print(" • Bạn có thể gõ lệnh bất cứ lúc nào ở DÒNG DƯỚI CÙNG mà không bị gián đoạn.")
        print(" • Gõ 'help' để xem danh sách lệnh | 'quit' để dừng hệ thống.")
        print("=" * 76 + "\n")

    # --------------------------------------------------------------------------
    # QUẢN LÝ TIẾN TRÌNH BOT TELEGRAM VÀ SCHEDULER CHẠY NGẦM
    # --------------------------------------------------------------------------
    def start_background_bot(self):
        """Khởi động Father Bot Telegram + Scheduler trong luồng ngầm daemon"""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token or token == "YOUR_BOT_TOKEN_HERE":
            print("[!] CẢNH BÁO: Chưa cấu hình TELEGRAM_BOT_TOKEN trong file .env.")
            print("    -> Bot Telegram tạm tắt. Host CLI vẫn hoạt động bình thường.")
            print("    -> Thêm token vào .env rồi gõ 'bot start' để kích hoạt.\n")
            return

        if self.bot_is_running:
            print("[i] Bot Telegram đang chạy trong luồng nền.")
            return

        def _bot_worker():
            self.bot_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.bot_loop)
            try:
                self.bot_app = create_bot_app(token)
                self.bot_is_running = True
                # stop_signals=None là bắt buộc để python-telegram-bot không đăng ký signal trên luồng phụ
                self.bot_app.run_polling(
                    allowed_updates=None,
                    stop_signals=None,
                    close_loop=True
                )
            except Exception as e:
                logger.error(f"Lỗi tiến trình Father Bot: {e}")
            finally:
                self.bot_is_running = False

        self.bot_thread = threading.Thread(target=_bot_worker, name="FatherBotThread", daemon=True)
        self.bot_thread.start()
        time.sleep(1.0)
        print("[OK] Đã kích hoạt Father Bot Telegram & Auto-Scheduler trong luồng ngầm.")

    def stop_background_bot(self):
        """Dừng luồng ngầm bot một cách an toàn"""
        if not self.bot_is_running or not self.bot_app:
            print("[i] Bot Telegram hiện không chạy.")
            return

        print("[*] Đang dừng Father Bot Telegram & Scheduler...")
        try:
            if self.bot_app.running and self.bot_loop:
                self.bot_loop.call_soon_threadsafe(self.bot_app.stop_running)
            if self.bot_thread and self.bot_thread.is_alive():
                self.bot_thread.join(timeout=3.0)
        except Exception as e:
            logger.warning(f"Cảnh báo khi dừng bot: {e}")

        self.bot_is_running = False
        print("[OK] Đã dừng thành công Father Bot Telegram.")

    # --------------------------------------------------------------------------
    # CƠ CHẾ ĐỌC DÒNG LỆNH KHÔNG GIÁN ĐOẠN (LOG CUỘN TRÊN, INPUT Ở DƯỚI)
    # --------------------------------------------------------------------------
    def read_cmd(self) -> str:
        """
        Đọc lệnh với cơ chế giữ con trỏ luôn ở đáy màn hình:
        - Môi trường console tương tác: Dùng prompt_toolkit.patch_stdout
        - Môi trường khác / fallback: Dùng sys.stdin.readline() với FallbackStdoutProxy
        """
        if self.session is not None:
            try:
                from prompt_toolkit.patch_stdout import patch_stdout
                with patch_stdout(raw=True):
                    return self.session.prompt(self.cmd_prompt)
            except (EOFError, KeyboardInterrupt):
                return "quit"
            except Exception:
                # Nếu xảy ra lỗi buffer console bất ngờ, chuyển sang fallback
                pass

        # Chế độ Fallback an toàn
        self.is_waiting_input = True
        try:
            self.show_cmd_prompt()
            line = sys.stdin.readline()
            if not line:
                return "quit"
            return line.strip()
        except (EOFError, KeyboardInterrupt):
            return "quit"
        finally:
            self.is_waiting_input = False

    def do_quit(self):
        print("\n[*] Đang tắt hệ thống LazBot...")
        self.stop_background_bot()
        if web_server.is_running:
            web_server.stop()
        self.b_running = False
        print("Tạm biệt!\n")

    # --------------------------------------------------------------------------
    # CÁC HÀM XỬ LÝ LỆNH HOST CLI
    # --------------------------------------------------------------------------
    def cmd_help(self, argv: List[str], argc: int):
        print("""
DANH SÁCH CÁC LỆNH HỖ TRỢ TRÊN HOST CLI:
----------------------------------------------------------------------
 1. Giỏ hàng & Giá sản phẩm:
    • prices / list           : Xem bảng giá các mặt hàng đã lưu trong CSDL
    • cart / scan             : Quét giỏ hàng Lazada & tính Giá Cuối Cùng
    • track                   : Quét & kiểm tra biến động giá ngay lập tức

 2. Cài đặt Giá đáy Săn sale (Target Price):
    • setprice <STT/Tên> <Giá>: Cài mức giá đáy (VD: setprice 1 100k, setprice 2 45k)
    • delprice <STT/all>      : Xóa mức giá đáy (VD: delprice 1, delprice all)
    • targets / target        : Xem danh sách các mặt hàng đang cài giá đáy

 3. Tài khoản & Cookie Lazada:
    • cookie status           : Kiểm tra trạng thái đăng nhập cookie
    • cookie set <chuỗi>      : Nạp cookie mới vào hệ thống

 4. Quản lý Bot Telegram & Auto-Scheduler:
    • bot status              : Xem trạng thái luồng bot Telegram & scheduler
    • bot start               : Khởi động lại bot Telegram chạy ngầm
    • bot stop                : Tạm dừng bot Telegram và scheduler
    • bot restart             : Khởi động lại luồng bot

 5. Giao diện Web CLI qua mạng nội bộ (LAN):
    • web / web status        : Xem địa chỉ IP LAN và cổng truy cập web
    • web start [cổng]        : Khởi động máy chủ Web Terminal (mặc định: 8080)
    • web stop                : Tắt máy chủ Web Terminal

 6. Quản lý CSDL SQLite (lazbot.db):
    • db info                 : Xem thống kê dung lượng và các bảng dữ liệu
    • db backup               : Tạo bản sao lưu dự phòng cho CSDL

 7. Tiện ích hệ thống:
    • clear / cls             : Xóa màn hình console
    • quit / exit / q         : Thoát chương trình
----------------------------------------------------------------------
""")

    def cmd_prices(self, argv: List[str], argc: int):
        items = database.get_cart_items_db()
        if not items:
            print("[!] Chưa có dữ liệu giỏ hàng. Hãy chạy lệnh 'cart' để quét trước.")
            return

        summary = database.get_cart_summary_db()
        total_val = summary.get("Total", "0₫") if summary else "0₫"
        updated_at = summary.get("updated_at", "N/A") if summary else "N/A"

        print("\n" + "=" * 90)
        print(f"  GIỎ HÀNG LAZADA (Tổng: {total_val} | Cập nhật: {updated_at})")
        print("=" * 90)
        print(f"{'STT':<4} | {'Tên sản phẩm':<32} | {'Phân loại':<24} | {'Giá':<12} | {'Giá đáy':<10}")
        print("-" * 90)

        for p in items:
            stt = p["stt"]
            name = p["name"][:30]
            sku = (p.get("sku") or "")[:22]
            price = p.get("price") or 0
            price_str = f"{price:,.0f}₫"

            target_p = database.get_target_price_db(p["pid"])
            target_str = f"≤ {target_p:,.0f}₫" if target_p else "---"

            valid_str = "" if p.get("valid", True) else " [Hết hàng]"
            print(f"{stt:<4} | {name:<32} | {sku:<24} | {price_str:<12} | {target_str:<10}{valid_str}")

        print("-" * 90)
        print(f"Tổng: {len(items)} mặt hàng.\n")

    def cmd_targets(self, argv: List[str], argc: int):
        targets = database.get_all_target_prices_db()
        if not targets:
            print("\n[i] Chưa có sản phẩm cài giá đáy. Dùng: setprice <STT> <giá>\n")
            return

        print("\n" + "=" * 95)
        print("  MỤC TIÊU GIÁ ĐÁY")
        print("=" * 95)
        print(f"{'STT':<4} | {'Tên sản phẩm':<30} | {'Phân loại':<24} | {'Hiện tại':<12} | {'Mục tiêu':<12} | {'Trạng thái'}")
        print("-" * 95)

        for t in targets:
            stt = str(t.get("stt") or "-")
            name = t.get("name", "Sản phẩm")[:28]
            sku = (t.get("sku") or "")[:22]
            target_p = t.get("target_price", 0)
            curr_p = t.get("current_price")
            is_active = t.get("is_active", 1)

            curr_str = f"{curr_p:,.0f}₫" if curr_p else "N/A"
            target_str = f"≤ {target_p:,.0f}₫"

            if not is_active or t.get("stt") is None:
                status = "Vô hiệu (Ngoài giỏ)"
            elif curr_p is None:
                status = "Chờ quét"
            elif curr_p <= target_p:
                status = "ĐÃ ĐẠT"
            else:
                diff = curr_p - target_p
                status = f"Thiếu {diff:,.0f}₫"

            print(f"{stt:<4} | {name:<30} | {sku:<24} | {curr_str:<12} | {target_str:<12} | {status}")

        print("-" * 95)
        print(f"Theo dõi: {len(targets)} sản phẩm.\n")

    def cmd_setprice(self, argv: List[str], argc: int):
        if argc < 3:
            print("[!] Cú pháp: setprice <STT hoặc Tên> <Mức giá>")
            print("    Ví dụ: setprice 1 100k, setprice 2 45.000, setprice ugreen 50k")
            return

        query = argv[1]
        price_str = argv[2]
        target_val = database.parse_user_price(price_str)
        if not target_val or target_val <= 0:
            print(f"[!] Mức giá '{price_str}' không hợp lệ. Hỗ trợ: 100k, 1.5tr, 50000, 45.000")
            return

        matched = database.find_product_by_stt_or_query(query)
        if not matched:
            print(f"[!] Không tìm thấy sản phẩm khớp với '{query}'. Gõ 'prices' để xem danh sách STT.")
            return

        pid = matched["pid"]
        name = matched["name"]
        sku = matched.get("sku", "")
        stt = matched["stt"]
        curr_p = matched.get("price") or 0

        database.set_target_price_db(pid, name, sku, target_val, matched.get("url", ""))

        print("\n[OK] ĐÃ CÀI ĐẶT GIÁ ĐÁY THÀNH CÔNG!")
        print(f"• Sản phẩm #{stt}: {name}")
        if sku:
            print(f"• Phân loại: {sku}")
        print(f"• Giá hiện tại : {curr_p:,.0f}₫")
        print(f"• Giá đáy nhận báo: ≤ {target_val:,.0f}₫\n")

    def cmd_delprice(self, argv: List[str], argc: int):
        if argc < 2:
            print("[!] Cú pháp: delprice <STT hoặc Tên hoặc 'all'>")
            return

        query = argv[1]
        if query.lower() in ("all", "tat ca", "tất cả"):
            cnt = database.clear_all_target_prices_db()
            print(f"[OK] Đã xóa toàn bộ {cnt} mức giá đáy.")
            return

        matched = database.find_product_by_stt_or_query(query)
        if not matched:
            print(f"[!] Không tìm thấy sản phẩm khớp với '{query}'.")
            return

        pid = matched["pid"]
        stt = matched["stt"]
        name = matched["name"]

        if database.remove_target_price_db(pid):
            print(f"[OK] Đã xóa giá đáy cho SP #{stt}: {name[:50]}")
        else:
            print(f"[i] Sản phẩm #{stt} chưa được cài đặt giá đáy.")

    def cmd_cart(self, argv: List[str], argc: int):
        from price_tracker import scrape_cart
        print("[*] Đang mở trình duyệt headless để quét giỏ hàng Lazada và tính Giá Cuối Cùng...")
        res = scrape_cart(headless=True)
        if res.get("status") == "ok":
            products = res.get("products", [])
            summary = res.get("summary", {})
            database.save_cart_to_db(products, summary)
            print(f"[OK] Đã quét thành công {len(products)} phân loại sản phẩm!")
            print(f"     Tổng tiền giỏ: {summary.get('Total', '0₫')}")
            self.cmd_prices([], 0)
        else:
            print(f"[!] Lỗi quét giỏ: {res.get('message')}")

    def cmd_track(self, argv: List[str], argc: int):
        from price_tracker import track_prices
        print("[*] Đang kiểm tra biến động giá tất cả sản phẩm trong giỏ...")
        res = track_prices(headless=True)
        if res.get("status") == "ok":
            changes = res.get("changes", [])
            total_change = res.get("total_change")
            total_p = res.get("total_products", 0)
            summary = res.get("summary", {})
            print(f"[OK] Đã kiểm tra {total_p} sản phẩm. Tổng tiền: {summary.get('Total', '0₫')}")
            if changes or total_change:
                print(f"\n[!] PHÁT HIỆN {len(changes)} BIẾN ĐỘNG:")
                if total_change:
                    print(
                        f"• Tổng giỏ hàng: {total_change['old_total']} -> {total_change['new_total']} "
                        f"({total_change['direction']} {abs(total_change['diff']):,.0f}₫)"
                    )
                for c in changes:
                    c_type = c.get("type", "PRICE_CHANGE")
                    sku_val = (c.get("sku") or "").strip()
                    sku_part = f" | {sku_val}" if sku_val else ""
                    name_part = (c.get("name") or "Sản phẩm")[:40]
                    if c_type == "STOCK_CHANGE":
                        price_val = c.get("price")
                        price_str = f" (Giá: {price_val:,.0f}₫)" if price_val else ""
                        print(f"• {name_part}{sku_part}: Tồn kho -> {c.get('status', 'THAY ĐỔI')}{price_str}")
                    elif c.get("old_price") is not None and c.get("new_price") is not None:
                        diff_val = c.get("diff")
                        if diff_val is None:
                            diff_val = c["new_price"] - c["old_price"]
                        direction = c.get("direction") or ("GIẢM" if diff_val < 0 else "TĂNG")
                        print(
                            f"• {name_part}{sku_part}: {c['old_price']:,.0f}₫ -> {c['new_price']:,.0f}₫ "
                            f"({direction} {abs(diff_val):,.0f}₫)"
                        )
                    else:
                        price_val = c.get("new_price") or c.get("price")
                        price_str = f"{price_val:,.0f}₫" if price_val else "N/A"
                        print(f"• {name_part}{sku_part}: Giá hiện tại {price_str}")
            else:
                print("[OK] Tất cả sản phẩm giữ nguyên giá.")
        else:
            print(f"[!] Lỗi: {res.get('message')}")

    def cmd_cookie(self, argv: List[str], argc: int):
        if argc < 2 or argv[1] == "status":
            cookies = cookie_manager.load_saved_cookies()
            if not cookies:
                print("\n[!] Hiện chưa có cookie Lazada nào được lưu.")
                print("    -> Dùng: cookie set <chuỗi_cookie_json>\n")
                return

            names = [c.get("name") for c in cookies]
            has_auth = any(n in names for n in ["t_uid", "lzd_sid", "epssw", "t_sid"])
            status_str = "🟢 ĐÃ XÁC THỰC TÀI KHOẢN (Auth Active)" if has_auth else "🟡 Cookie khách (Guest)"

            print("\n" + "=" * 60)
            print("  TRẠNG THÁI COOKIE LAZADA")
            print("=" * 60)
            print(f"• Tổng số cookie đã lưu: {len(cookies)}")
            print(f"• Trạng thái đăng nhập  : {status_str}")
            print(f"• Session tokens       : {', '.join([n for n in ['t_uid', 'lzd_sid', 'epssw'] if n in names]) or 'Không'}")
            print("=" * 60 + "\n")
        elif argv[1] == "set":
            if argc < 3:
                print("[!] Cú pháp: cookie set <chuỗi_cookie>")
                return
            full_str = " ".join(argv[2:])
            cookies = cookie_manager.parse_cookie_input(full_str)
            if cookies and len(cookies) > 0:
                count = cookie_manager.save_cookies_list(cookies)
                print(f"[OK] Đã nhận diện và lưu thành công {count} cookies vào cookies.json.")
            else:
                print("[!] Không nhận diện được định dạng cookie hợp lệ.")
        else:
            print("[!] Cú pháp: cookie [status | set <chuỗi_cookie>]")

    def cmd_bot(self, argv: List[str], argc: int):
        action = argv[1].lower() if argc >= 2 else "status"

        if action == "status":
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            has_token = bool(token and token != "YOUR_BOT_TOKEN_HERE")
            masked_token = f"{token[:8]}...{token[-4:]}" if has_token else "Chưa cấu hình"
            sub_count = len(get_subscribers())
            auto_track = "BẬT" if is_auto_track_enabled() else "TẮT"

            print("\n" + "=" * 65)
            print("  TRẠNG THÁI FATHER BOT TELEGRAM & AUTO-SCHEDULER")
            print("=" * 65)
            if self.bot_is_running:
                print("• Trạng thái tiến trình : 🟢 ĐANG CHẠY TRONG TIẾN TRÌNH NỀN (IN-PROCESS)")
            else:
                print("• Trạng thái tiến trình : 🔴 ĐÃ DỪNG (STOPPED)")
            print(f"• Bot Token             : {masked_token}")
            print(f"• Số người đăng ký (Sub): {sub_count} người dùng")
            print(f"• Quét tự động (Auto)   : {auto_track}")
            print("• Điều khiển            : 'bot start', 'bot stop', 'bot restart'")
            print("=" * 65 + "\n")

        elif action == "start":
            if self.bot_is_running:
                print("[i] Bot Telegram đang chạy rồi.")
            else:
                self.start_background_bot()

        elif action == "stop":
            self.stop_background_bot()

        elif action == "restart":
            self.stop_background_bot()
            time.sleep(1.0)
            self.start_background_bot()

        else:
            print("[!] Cú pháp: bot [status | start | stop | restart]")

    def cmd_web(self, argv: List[str], argc: int):
        action = argv[1].lower() if argc >= 2 else "status"

        if action == "status":
            lan_ip = web_server.lan_ip
            port = web_server.port
            clients = len(web_server.clients)
            status_str = "🟢 ĐANG CHẠY (ONLINE)" if web_server.is_running else "🔴 ĐÃ DỪNG (STOPPED)"

            print("\n" + "=" * 65)
            print("  TRẠNG THÁI MÁY CHỦ WEB CLI CONSOLE (MẠNG NỘI BỘ LAN)")
            print("=" * 65)
            print(f"• Trạng thái máy chủ   : {status_str}")
            print(f"• Địa chỉ LAN truy cập : http://{lan_ip}:{port}")
            print(f"• Địa chỉ Localhost    : http://127.0.0.1:{port}")
            print(f"• Thiết bị đang nối web: {clients} kết nối")
            print("• Điều khiển           : 'web start [port]', 'web stop'")
            print("=" * 65 + "\n")

        elif action == "start":
            if web_server.is_running:
                print(f"[i] Web CLI đang chạy tại http://{web_server.lan_ip}:{web_server.port}")
                return
            port = int(argv[2]) if argc >= 3 and argv[2].isdigit() else 8080
            web_server.set_cli(self)
            web_server.start(port)
            print(f"[OK] Đã khởi động Web CLI thành công tại: http://{web_server.lan_ip}:{port}")

        elif action == "stop":
            if not web_server.is_running:
                print("[i] Web CLI hiện không chạy.")
                return
            web_server.stop()
            print("[OK] Đã tắt Web CLI Server.")

        else:
            print("[!] Cú pháp: web [status | start <cổng> | stop]")

    def cmd_db(self, argv: List[str], argc: int):
        action = argv[1].lower() if argc >= 2 else "info"

        if action == "info":
            db_path = database.DB_PATH
            if not os.path.exists(db_path):
                print(f"[!] Database chưa tồn tại tại {db_path}")
                return

            size_kb = os.path.getsize(db_path) / 1024
            conn = database.get_connection()
            cart_cnt = conn.execute("SELECT COUNT(*) FROM cart_items").fetchone()[0]
            hist_cnt = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
            target_cnt = conn.execute("SELECT COUNT(*) FROM target_prices").fetchone()[0]
            sub_cnt = conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]

            print("\n" + "=" * 60)
            print("  THÔNG TIN CƠ SỞ DỮ LIỆU SQLITE (lazbot.db)")
            print("=" * 60)
            print(f"• Đường dẫn tệp       : {db_path}")
            print(f"• Dung lượng tệp      : {size_kb:.2f} KB")
            print(f"• Sản phẩm trong giỏ  : {cart_cnt} mặt hàng")
            print(f"• Bản ghi lịch sử giá : {hist_cnt} lần biến động")
            print(f"• Mặt hàng cài giá đáy: {target_cnt} sản phẩm")
            print(f"• Người nhận cảnh báo : {sub_cnt} subscribers")
            print("=" * 60 + "\n")

        elif action == "backup":
            import shutil
            db_path = database.DB_PATH
            if not os.path.exists(db_path):
                print("[!] Chưa có file lazbot.db để sao lưu.")
                return
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(BASE_DIR, f"lazbot_backup_{ts}.db")
            try:
                shutil.copy2(db_path, backup_path)
                print(f"[OK] Đã sao lưu database thành công:")
                print(f"     -> {backup_path}")
            except Exception as e:
                print(f"[!] Lỗi sao lưu: {e}")
        else:
            print("[!] Cú pháp: db [info | backup]")

    def cmd_clear(self, argv: List[str], argc: int):
        self.clear_screen()
        self.print_banner()

    # --------------------------------------------------------------------------
    # ĐIỀU HÀNH CHÍNH (RUN)
    # --------------------------------------------------------------------------
    def run(self, init_argv: Optional[List[str]] = None):
        # 0. Chế độ chạy ngầm / Server daemon (không mở console nhập lệnh, phù hợp Termux/VPS/nohup)
        is_daemon = bool(init_argv and any(arg in init_argv for arg in ("--bot", "--daemon", "-d", "--service")))
        if is_daemon:
            self.init_console()
            self.init_cmd()
            self.start_background_bot()

            enable_web = bool(init_argv and any(arg in init_argv for arg in ("--web", "-w"))) or (os.getenv("ENABLE_WEB_CLI", "").lower() in ("true", "1", "yes"))
            if enable_web:
                web_port = 8080
                for i, arg in enumerate(init_argv or []):
                    if arg in ("--port", "-p") and i + 1 < len(init_argv) and init_argv[i + 1].isdigit():
                        web_port = int(init_argv[i + 1])
                web_server.set_cli(self)
                web_server.start(web_port)
                print(f"[OK] Đã kích hoạt Web CLI Console tại: http://{web_server.lan_ip}:{web_port}\n")

            print("[*] Bot và Lịch quét đang chạy ở chế độ nền (Daemon). Nhấn Ctrl+C để dừng.\n")
            try:
                while True:
                    time.sleep(1)
            except (KeyboardInterrupt, SystemExit):
                self.do_quit()
            return

        # 1. Nếu có tham số dòng lệnh một lần (One-shot CLI command)
        if init_argv and len(init_argv) > 1:
            first_arg = init_argv[1].lower()
            if first_arg not in ("--no-bot", "--web", "-w", "--bot", "--daemon", "-d", "--service"):
                self.init_console()
                self.init_cmd()
                if first_arg in self.cmd_do_func:
                    self.do_cmd(first_arg, init_argv[1:], len(init_argv[1:]))
                elif first_arg in ("quit", "exit", "q"):
                    pass
                else:
                    self.do_unknown()
                return

        # 2. Khởi động môi trường tương tác REPL toàn diện
        self.init_console()
        self.init_cmd()

        # Thiết lập Fallback stdout proxy nếu không dùng prompt_toolkit
        if self.session is None:
            sys.stdout = FallbackStdoutProxy(
                sys.stdout,
                lambda: self.cmd_prompt,
                lambda: self.is_waiting_input
            )
            sys.stderr = FallbackStdoutProxy(
                sys.stderr,
                lambda: self.cmd_prompt,
                lambda: self.is_waiting_input
            )

        # 3. Kích hoạt bot Telegram & Auto Scheduler trong luồng ngầm
        disable_bot = bool(init_argv and "--no-bot" in init_argv)
        if not disable_bot:
            self.start_background_bot()

        # 4. Kích hoạt Web Terminal Server nếu có tham số --web / -w hoặc biến môi trường
        enable_web = bool(init_argv and any(arg in init_argv for arg in ("--web", "-w"))) or (os.getenv("ENABLE_WEB_CLI", "").lower() in ("true", "1", "yes"))
        if enable_web:
            web_port = 8080
            for i, arg in enumerate(init_argv or []):
                if arg in ("--port", "-p") and i + 1 < len(init_argv) and init_argv[i + 1].isdigit():
                    web_port = int(init_argv[i + 1])
            web_server.set_cli(self)
            web_server.start(web_port)
            print(f"[OK] Đã kích hoạt Web CLI Console tại: http://{web_server.lan_ip}:{web_port}\n")

        # 5. Vòng lặp tương tác REPL
        self.b_running = True
        try:
            while self.b_running:
                line = self.read_cmd()
                name, argv = self.parse_cmd(line)
                if not name:
                    continue
                if name in ("quit", "exit", "q"):
                    self.do_quit()
                    break
                if name in self.cmd_do_func:
                    self.do_cmd(name, argv, len(argv))
                else:
                    self.do_unknown()
        except (KeyboardInterrupt, SystemExit):
            self.do_quit()


# ==============================================================================
# ĐIỂM BẮT ĐẦU CHƯƠNG TRÌNH
# ==============================================================================
def main():
    cli = LazBotMainCLI("LazBot> ")
    cli.run(sys.argv)


if __name__ == "__main__":
    main()
