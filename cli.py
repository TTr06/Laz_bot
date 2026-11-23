"""
CmdLineInterface & LazBotCLI (Python Host CLI)
Cài đặt kiến trúc hướng đối tượng kế thừa chuẩn theo mẫu CmdLineInterface (cli.h),
chạy trực tiếp trên Python thuần không cần cài compiler g++ hay biên dịch.
"""

import os
import sys
import shlex
from datetime import datetime

# Đảm bảo UTF-8
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import database
import cookie_manager


class CmdLineInterface:
    """
    Lớp cơ sở giao diện dòng lệnh (mô phỏng chính xác lớp CmdLineInterface từ cli.h)
    """

    def __init__(self, prompt: str = "LazBot> "):
        self.cmd_prompt = prompt
        self.b_running = True
        self.cmd_do_func = {}
        self.cmd_name_list = []
        self.cmd_default_id = None

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
        """Ghi đè trong lớp kế thừa để đăng ký lệnh"""
        pass

    def init_console(self):
        """Ghi đè trong lớp kế thừa để khởi tạo console / in banner"""
        pass

    def read_cmd(self) -> str:
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            return "quit"

    def parse_cmd(self, line: str) -> tuple[str, list[str]]:
        """
        Phân tích chuỗi lệnh, hỗ trợ đối số có dấu ngoặc kép ""
        """
        line = line.strip()
        if not line:
            return "", []

        try:
            tokens = shlex.split(line)
        except ValueError:
            tokens = line.split()

        if not tokens:
            return "", []

        cmd_name = tokens[0].lower()
        return cmd_name, tokens

    def do_unknown(self):
        print("Lệnh không hợp lệ. Gõ 'help' để xem danh sách các lệnh hỗ trợ.")

    def do_quit(self):
        self.b_running = False
        print("Tạm biệt!")

    def do_cmd(self, name: str, cmd_argv: list[str], cmd_argc: int):
        func = self.cmd_do_func.get(name.lower())
        if func:
            func(cmd_argv, cmd_argc)

    def run(self, init_argv: list[str] = None):
        """
        Chạy CLI:
        - Nếu có tham số init_argv (one-shot): thực thi 1 lệnh rồi thoát
        - Nếu không có tham số: chạy vòng lặp tương tác REPL
        """
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


class LazBotCLI(CmdLineInterface):
    """
    Lớp CLI trên Host kế thừa trực tiếp từ CmdLineInterface
    """

    def __init__(self, prompt: str = "LazBot> "):
        super().__init__(prompt)

    def init_console(self):
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
        self.add_cmd("db", self.cmd_db)
        self.add_cmd("clear", self.cmd_clear)
        self.add_cmd("cls", self.cmd_clear)

    def print_banner(self):
        print("=" * 70)
        print("          LAZADA TRACKER & BOT MANAGER - HOST CLI")
        print("          (Kế thừa từ CmdLineInterface - Python Native)")
        print("=" * 70)
        print(" Gõ 'help' để xem danh sách các lệnh hỗ trợ.")
        print(" Gõ 'quit' hoặc 'exit' để thoát khỏi giao diện dòng lệnh.")
        print("=" * 70 + "\n")

    def cmd_help(self, argv: list[str], argc: int):
        print("""
DANH SÁCH CÁC LỆNH HỖ TRỢ TRÊN HOST CLI:
----------------------------------------------------------------------
 1. Giỏ hàng & Giá sản phẩm:
    • prices / list           : Xem bảng giá các mặt hàng đã lưu trong CSDL
    • cart / scan             : Quét giỏ hàng Lazada & tính Giá Cuối Cùng
    • track                   : Quét & kiểm tra biến động giá ngay lập tức

 2. Cài đặt Giá đáy Săn sale (Target Price):
    • setprice <STT/Tên> <Giá>: Cài mức giá đáy (VD: setprice 1 100k)
    • delprice <STT/all>      : Xóa mức giá đáy (VD: delprice 1, delprice all)
    • targets                 : Xem danh sách các mặt hàng đang cài giá đáy

 3. Tài khoản & Cookie Lazada:
    • cookie status           : Kiểm tra trạng thái đăng nhập cookie
    • cookie set <chuỗi>      : Nạp cookie mới vào hệ thống

 4. Quản lý Bot Telegram trên Host:
    • bot status              : Kiểm tra bot Telegram có đang chạy không
    • bot start               : Khởi động bot Telegram chạy nền trên host
    • bot stop                : Dừng tiến trình bot Telegram

 5. Quản lý CSDL SQLite (lazbot.db):
    • db info                 : Xem thống kê dung lượng và các bảng dữ liệu
    • db backup               : Tạo bản sao lưu dự phòng cho CSDL

 6. Tiện ích hệ thống:
    • clear / cls             : Xóa màn hình console
    • quit / exit / q         : Thoát chương trình
----------------------------------------------------------------------
""")

    def cmd_prices(self, argv: list[str], argc: int):
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

    def cmd_targets(self, argv: list[str], argc: int):
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

    def cmd_setprice(self, argv: list[str], argc: int):
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

    def cmd_delprice(self, argv: list[str], argc: int):
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

    def cmd_cart(self, argv: list[str], argc: int):
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

    def cmd_track(self, argv: list[str], argc: int):
        from price_tracker import track_prices
        print("[*] Đang kiểm tra biến động giá tất cả sản phẩm trong giỏ...")
        res = track_prices(headless=True)
        if res.get("status") == "ok":
            changes = res.get("changes", [])
            total_p = res.get("total_products", 0)
            summary = res.get("summary", {})
            print(f"[OK] Đã kiểm tra {total_p} sản phẩm. Tổng tiền: {summary.get('Total', '0₫')}")
            if changes:
                print(f"\n[!] PHÁT HIỆN {len(changes)} BIẾN ĐỘNG GIÁ:")
                for c in changes:
                    print(f"• {c['name'][:40]} | {c.get('sku', '')}: {c['old_price']:,.0f}₫ -> {c['new_price']:,.0f}₫ ({c['direction']} {abs(c['diff']):,.0f}₫)")
            else:
                print("[OK] Tất cả sản phẩm giữ nguyên giá.")
        else:
            print(f"[!] Lỗi: {res.get('message')}")

    def cmd_cookie(self, argv: list[str], argc: int):
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

    def cmd_bot(self, argv: list[str], argc: int):
        import subprocess
        action = argv[1].lower() if argc >= 2 else "status"

        if action == "status":
            is_running = False
            pids = []
            if sys.platform == "win32":
                try:
                    out = subprocess.check_output('wmic process where "name=\'python.exe\'" get ProcessId,CommandLine', shell=True, text=True, errors="replace")
                    for line in out.splitlines():
                        if "bot.py" in line:
                            parts = line.strip().split()
                            if parts and parts[-1].isdigit():
                                pids.append(parts[-1])
                                is_running = True
                except Exception:
                    pass
            else:
                try:
                    out = subprocess.check_output("ps aux | grep '[b]ot.py'", shell=True, text=True, errors="replace")
                    for line in out.splitlines():
                        parts = line.split()
                        if len(parts) >= 2:
                            pids.append(parts[1])
                            is_running = True
                except Exception:
                    pass

            print("\n" + "=" * 60)
            print("  TRẠNG THÁI TIẾN TRÌNH BOT TELEGRAM TRÊN HOST")
            print("=" * 60)
            if is_running:
                print(f"• Trạng thái : 🟢 ĐANG CHẠY (RUNNING)")
                print(f"• Process IDs: {', '.join(pids)}")
                print("• Dừng bot   : Gõ 'bot stop'")
            else:
                print("• Trạng thái : 🔴 ĐÃ DỪNG (STOPPED)")
                print("• Khởi động  : Gõ 'bot start'")
            print("=" * 60 + "\n")

        elif action == "start":
            bot_file = os.path.join(BASE_DIR, "bot.py")
            print("[*] Đang khởi động bot Telegram trong tiến trình nền...")
            if sys.platform == "win32":
                creation_flags = 0x00000008 | 0x00000200
                subprocess.Popen([sys.executable, bot_file], creationflags=creation_flags, close_fds=True)
            else:
                subprocess.Popen([sys.executable, bot_file], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time
            time.sleep(1.5)
            print("[OK] Đã gửi lệnh khởi động bot.")
            self.cmd_bot(["bot", "status"], 2)

        elif action == "stop":
            print("[*] Đang tìm và dừng các tiến trình bot.py...")
            stopped = False
            if sys.platform == "win32":
                try:
                    out = subprocess.check_output('wmic process where "name=\'python.exe\'" get ProcessId,CommandLine', shell=True, text=True, errors="replace")
                    for line in out.splitlines():
                        if "bot.py" in line:
                            parts = line.strip().split()
                            if parts and parts[-1].isdigit():
                                pid = parts[-1]
                                subprocess.call(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                print(f"[OK] Đã dừng tiến trình PID: {pid}")
                                stopped = True
                except Exception as e:
                    print(f"[!] Lỗi khi dừng: {e}")
            else:
                try:
                    subprocess.call("pkill -f 'bot.py'", shell=True)
                    stopped = True
                except Exception:
                    pass

            if not stopped:
                print("[i] Không tìm thấy tiến trình bot.py nào đang chạy.")
            else:
                print("[OK] Hoàn tất.")

        else:
            print("[!] Cú pháp: bot [status | start | stop]")

    def cmd_db(self, argv: list[str], argc: int):
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

    def cmd_clear(self, argv: list[str], argc: int):
        self.clear_screen()
        self.print_banner()


if __name__ == "__main__":
    cli = LazBotCLI("LazBot> ")
    cli.run(sys.argv)
