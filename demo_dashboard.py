"""
Father Bot - Host Terminal CLI Dashboard (DEMO)
Giao diện dòng lệnh trực quan cho host bot:
- Cột bên trái: Danh sách sản phẩm, các phân loại (SKU), giá thực tế, giá gốc, biến động và tổng tiền giỏ hàng.
- Cột bên phải: Nhật ký hoạt động (Live Logs) thời gian thực, trạng thái lịch quét (1 phút/lần), thống kê hệ thống.

* Đây là bản DEMO độc lập để trải nghiệm giao diện trước khi tích hợp vào tool chính.
* Chạy: python demo_dashboard.py
"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import json
import os
import random
import time
from datetime import datetime, timedelta

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICE_HISTORY_FILE = os.path.join(BASE_DIR, "price_history.json")


def load_demo_products():
    """Tải dữ liệu sản phẩm thực tế từ price_history.json nếu có, hoặc dùng dữ liệu mẫu"""
    products = []
    summary = {
        "Total": "1,642,000₫",
        "Subtotal": "2,150,000₫",
        "Promotion": "-508,000₫",
        "Shipping Fee": "0₫"
    }

    if os.path.exists(PRICE_HISTORY_FILE):
        try:
            with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                prods_dict = data.get("products", {})
                if prods_dict:
                    idx = 1
                    for pid, p in prods_dict.items():
                        price = p.get("current_price") or 0
                        base = p.get("base_price") or price
                        sku = p.get("sku", "").strip() or "Mặc định"
                        valid = p.get("valid", True)
                        
                        # Tính biến động nếu có lịch sử
                        history = p.get("price_history", [])
                        diff_pct = 0
                        if len(history) >= 2:
                            old = history[-2]["price"]
                            if old > 0:
                                diff_pct = round(((price - old) / old) * 100, 1)

                        products.append({
                            "id": idx,
                            "name": p.get("name", "Sản phẩm Lazada"),
                            "sku": sku,
                            "price": price,
                            "base_price": base,
                            "valid": valid,
                            "diff_pct": diff_pct
                        })
                        idx += 1
                if data.get("order_summary"):
                    summary = data["order_summary"]
        except Exception:
            pass

    # Nếu không có dữ liệu thật thì nạp mock data
    if not products:
        products = [
            {
                "id": 1,
                "name": "Trạm Sạc Ugreen S6 Magic Cube 20w 30w 65w 2500w 8 in 1",
                "sku": "Đen 65w",
                "price": 489000,
                "base_price": 787000,
                "valid": True,
                "diff_pct": -37.8
            },
            {
                "id": 2,
                "name": "Cáp Sạc Nhanh Từ Tính Magnetic Braided 60W",
                "sku": "Màu đen [20CM - Type C]",
                "price": 69000,
                "base_price": 99000,
                "valid": True,
                "diff_pct": 0
            },
            {
                "id": 3,
                "name": "Củ sạc PISEN 65W GaN Fast Charger gập gọn",
                "sku": "GaN 65W Ba Cổng",
                "price": 320000,
                "base_price": 450000,
                "valid": True,
                "diff_pct": -12.5
            },
            {
                "id": 4,
                "name": "Kính cường lực SmartDevil Gaming Anti-blue",
                "sku": "2 miếng [Xiaomi 17T Pro]",
                "price": 145000,
                "base_price": 180000,
                "valid": True,
                "diff_pct": 0
            },
            {
                "id": 5,
                "name": "Tai nghe MoonDrop Portable USB-C HIFI DAC",
                "sku": "Bình minh 2",
                "price": 850000,
                "base_price": 850000,
                "valid": False,
                "diff_pct": 0
            },
            {
                "id": 6,
                "name": "Đệm tai nghe Air-pressure Balanced Ear Tips",
                "sku": "Size M T500B",
                "price": 49000,
                "base_price": 60000,
                "valid": True,
                "diff_pct": 0
            }
        ]

    return products, summary


class DashboardDemo:
    def __init__(self):
        self.console = Console()
        self.products, self.summary = load_demo_products()
        self.start_time = datetime.now()
        self.logs = []
        self.total_checks = 18
        self.subscribers_count = 2
        self.cycle_seconds = 60
        self.next_check_countdown = 35

        # Khởi tạo một số log ban đầu
        init_logs = [
            ("INFO", "Hệ thống Father Bot khởi động thành công trên host."),
            ("INFO", "Đã nạp thành công 15 cookies Lazada với đầy đủ phiên auth."),
            ("SUCCESS", "Trình duyệt Anti-Detect Stealth Driver sẵn sàng (CDP Bypass)."),
            ("INFO", "Scheduler khởi động: Lịch quét tự động 1 phút/lần."),
            ("SUCCESS", f"Đã kết nối Telegram Bot. Đang phục vụ {self.subscribers_count} subscribers."),
            ("INFO", "Lượt quét lúc 13:20:00: Đã quét 10 sản phẩm trong giỏ hàng."),
            ("ALERT", "Phát hiện biến động giá: 'Trạm Sạc Ugreen' giảm 37.8%!"),
            ("SUCCESS", "Đã gửi cảnh báo biến động kèm SKU & Link mua hàng qua Telegram."),
            ("INFO", "Đang chờ đến chu kỳ quét tiếp theo...")
        ]
        t = datetime.now() - timedelta(minutes=2)
        for level, msg in init_logs:
            self.logs.append({
                "time": t.strftime("%H:%M:%S"),
                "level": level,
                "msg": msg
            })
            t += timedelta(seconds=12)

    def add_log(self, level: str, msg: str):
        now_str = datetime.now().strftime("%H:%M:%S")
        self.logs.append({
            "time": now_str,
            "level": level,
            "msg": msg
        })
        if len(self.logs) > 30:
            self.logs.pop(0)

    def make_header(self) -> Panel:
        now = datetime.now()
        uptime = str(now - self.start_time).split(".")[0]
        
        table = Table.grid(expand=True)
        table.add_column(justify="left", ratio=3)
        table.add_column(justify="center", ratio=4)
        table.add_column(justify="right", ratio=3)

        left_text = Text.from_markup("🤖 [bold white]FATHER BOT[/] [bold cyan]v2.5[/] | [bold green]● ONLINE[/]")
        center_text = Text.from_markup(f"⏰ Chu kỳ: [bold yellow]1 phút/lần[/] | ⏳ Kế tiếp: [bold cyan]{self.next_check_countdown}s[/]")
        right_text = Text.from_markup(f"👥 Sub: [bold green]{self.subscribers_count}[/] | ⏱️ Uptime: [bold white]{uptime}[/]")

        table.add_row(left_text, center_text, right_text)
        return Panel(table, style="bold white on navy_blue", box=box.ROUNDED)

    def make_products_panel(self) -> Panel:
        """Tạo bảng hiển thị chi tiết sản phẩm và giá bên cột trái"""
        table = Table(
            expand=True,
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            row_styles=["none", "dim"]
        )
        table.add_column("#", width=3, justify="center")
        table.add_column("Sản Phẩm & Phân Loại", ratio=5)
        table.add_column("Giá Cuối", justify="right", ratio=2)
        table.add_column("Giá Gốc", justify="right", ratio=2)
        table.add_column("Biến Động", justify="center", ratio=2)

        for p in self.products[:9]:
            name = p["name"][:38] + ("..." if len(p["name"]) > 38 else "")
            sku = p["sku"][:28]
            item_desc = f"[bold white]{name}[/]\n   [dim magenta]🏷️ {sku}[/]"

            if not p.get("valid", True):
                status_str = "[bold red]Hết hàng[/]"
                price_str = "[dim strike]N/A[/]"
                base_str = "[dim strike]N/A[/]"
                change_str = "[red]HẾT HÀNG[/]"
            else:
                price_str = f"[bold green]{p['price']:,.0f}₫[/]"
                if p["base_price"] and p["base_price"] > p["price"]:
                    base_str = f"[dim strike]{p['base_price']:,.0f}₫[/]"
                else:
                    base_str = "[dim]—[/]"

                diff = p.get("diff_pct", 0)
                if diff < 0:
                    change_str = f"[bold green]📉 {diff}%[/]"
                elif diff > 0:
                    change_str = f"[bold red]📈 +{diff}%[/]"
                else:
                    change_str = "[dim]—[/]"

            table.add_row(
                str(p["id"]),
                item_desc,
                price_str,
                base_str,
                change_str
            )

        # Phần tóm tắt giỏ hàng
        summary_grid = Table.grid(expand=True)
        summary_grid.add_column(justify="left", ratio=3)
        summary_grid.add_column(justify="right", ratio=3)

        total_str = self.summary.get("Total", "N/A")
        sub_str = self.summary.get("Subtotal", "N/A")
        promo_str = self.summary.get("Promotion", "0₫")

        summary_text = (
            f"💵 [bold yellow]TỔNG TIỀN THANH TOÁN:[/] [bold green]{total_str}[/]\n"
            f"[dim]Tạm tính: {sub_str} | Voucher giảm: {promo_str} | Ship: 0₫[/]"
        )

        left_content = Table.grid(expand=True)
        left_content.add_row(table)
        left_content.add_row(Text("━" * 50, style="dim"))
        left_content.add_row(Text.from_markup(summary_text))

        return Panel(
            left_content,
            title="[bold yellow]🛒 GIỎ HÀNG LAZADA (TẤT CẢ PHÂN LOẠI & GIÁ THỰC TẾ)[/]",
            border_style="yellow",
            box=box.ROUNDED
        )

    def make_logs_panel(self) -> Panel:
        """Tạo bảng nhật ký hoạt động (Live Logs) bên cột phải"""
        table = Table(
            expand=True,
            box=box.SIMPLE,
            header_style="bold cyan",
            show_header=False
        )
        table.add_column("Time", width=8, style="dim")
        table.add_column("Tag", width=9, justify="center")
        table.add_column("Message", ratio=1)

        level_styles = {
            "INFO": "[cyan]INFO[/]",
            "SUCCESS": "[bold green]OK[/]",
            "WARN": "[bold yellow]WARN[/]",
            "ALERT": "[bold red]ALERT[/]"
        }

        for item in self.logs[-14:]:
            tag = level_styles.get(item["level"], item["level"])
            msg_text = item["msg"]
            if item["level"] == "ALERT":
                msg_text = f"[bold red]{msg_text}[/]"
            elif item["level"] == "SUCCESS":
                msg_text = f"[green]{msg_text}[/]"

            table.add_row(item["time"], tag, msg_text)

        # Thống kê nhanh
        stats_text = (
            f"[bold cyan]⚡ Thống kê:[/]\n"
            f"• Lượt quét thành công: [bold green]{self.total_checks}[/] lần\n"
            f"• Tần suất kiểm tra: [bold yellow]1 phút/lần[/] (siêu tốc)\n"
            f"• Trạng thái Cookie: [bold green]Hợp lệ (Authenticated)[/]\n"
            f"• Thao tác giỏ: [bold green]Chỉ đọc giỏ hàng (Không bấm checkout)[/]"
        )

        right_content = Table.grid(expand=True)
        right_content.add_row(table)
        right_content.add_row(Text("━" * 40, style="dim"))
        right_content.add_row(Text.from_markup(stats_text))

        return Panel(
            right_content,
            title="[bold cyan]📜 NHẬT KÝ HOẠT ĐỘNG (LIVE LOGS)[/]",
            border_style="cyan",
            box=box.ROUNDED
        )

    def make_footer(self) -> Panel:
        text = Text.from_markup(
            "[dim]📌 [bold white]DEMO GIAO DIỆN HOST[/] | "
            "Nhấn [bold red]Ctrl + C[/] để thoát demo | "
            "Cột trái: Sản phẩm & Giá | Cột phải: Live Log 1p/lần[/]"
        )
        return Panel(text, style="white on dark_green", box=box.ROUNDED)

    def generate_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        layout["body"].split_row(
            Layout(name="left", ratio=6),
            Layout(name="right", ratio=4)
        )
        layout["header"].update(self.make_header())
        layout["left"].update(self.make_products_panel())
        layout["right"].update(self.make_logs_panel())
        layout["footer"].update(self.make_footer())
        return layout

    def run(self):
        """Vòng lặp chạy live dashboard mô phỏng thời gian thực"""
        simulated_events = [
            ("INFO", "Scheduler kích hoạt lượt quét giỏ hàng tự động."),
            ("INFO", "Anti-detect driver: Truy cập https://cart.lazada.vn/cart."),
            ("SUCCESS", "Đã cuộn trang tải toàn bộ danh sách và tick Chọn tất cả."),
            ("INFO", "Trích xuất giá và voucher áp dụng toàn giỏ hàng."),
            ("SUCCESS", "Tất cả sản phẩm & SKU vẫn giữ nguyên giá ổn định."),
            ("INFO", "Hoàn tất lượt quét trong 9.8s. Đang chờ chu kỳ tiếp theo."),
            ("ALERT", "⚡ FLASH SALE: 'Củ sạc PISEN 65W' vừa giảm thêm 20,000₫!"),
            ("SUCCESS", "Đã gửi thông báo kèm Link mua hàng tới Telegram Subscribers.")
        ]
        event_idx = 0

        with Live(self.generate_layout(), refresh_per_second=2, screen=True) as live:
            try:
                while True:
                    time.sleep(1)
                    self.next_check_countdown -= 1

                    # Khi countdown về 0 -> mô phỏng 1 lần check mới
                    if self.next_check_countdown <= 0:
                        self.next_check_countdown = self.cycle_seconds
                        self.total_checks += 1
                        self.add_log("INFO", f"Bắt đầu lượt quét tự động #{self.total_checks} (1 phút/lần)...")

                    # Cứ vài giây đẩy 1 event mô phỏng vào log
                    if self.next_check_countdown % 8 == 0:
                        ev_level, ev_msg = simulated_events[event_idx % len(simulated_events)]
                        self.add_log(ev_level, ev_msg)
                        event_idx += 1

                    live.update(self.generate_layout())

            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    demo = DashboardDemo()
    demo.run()
