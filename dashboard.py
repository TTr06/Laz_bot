"""
Host CLI Dashboard Module
Giao diện dòng lệnh 2 cột tinh gọn cho host bot:
- Cột trái: Giỏ hàng & Giá (sản phẩm, phân loại SKU, giá gốc, biến động).
- Cột phải: Nhật ký hệ thống & trạng thái (lượt quét, cookie, thời gian thực).
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich import box

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICE_HISTORY_FILE = os.path.join(BASE_DIR, "price_history.json")


class HostDashboard:
    def __init__(self):
        self.console = Console(legacy_windows=False)
        self.start_time = datetime.now()
        self.products: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}
        self.logs: List[Dict[str, str]] = []
        self.total_checks: int = 0
        self.subscribers_count: int = 0
        self.next_check_time: Optional[datetime] = None
        self.cookie_status: str = "OK"
        self.is_running: bool = False
        self.live: Optional[Live] = None

        self.load_initial_data()

    def load_initial_data(self):
        """Nạp dữ liệu giỏ hàng đã lưu trước đó nếu có"""
        if os.path.exists(PRICE_HISTORY_FILE):
            try:
                with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    prods = data.get("products", {})
                    idx = 1
                    for pid, p in prods.items():
                        price = p.get("current_price") or 0
                        base = p.get("base_price") or price
                        sku = p.get("sku", "").strip() or "Mặc định"
                        valid = p.get("valid", True)

                        history = p.get("price_history", [])
                        diff_pct = 0
                        if len(history) >= 2:
                            old = history[-2]["price"]
                            if old > 0:
                                diff_pct = round(((price - old) / old) * 100, 1)

                        self.products.append({
                            "id": idx,
                            "name": p.get("name", "Sản phẩm"),
                            "sku": sku,
                            "price": price,
                            "base_price": base,
                            "valid": valid,
                            "diff_pct": diff_pct
                        })
                        idx += 1

                    if data.get("order_summary"):
                        self.summary = data["order_summary"]
            except Exception:
                pass

    def update_cart(self, products: List[Dict[str, Any]], summary: Dict[str, Any]):
        """Cập nhật dữ liệu giỏ hàng mới nhất từ price_tracker"""
        updated_list = []
        for idx, p in enumerate(products, 1):
            price = p.get("price") or 0
            base = p.get("base_price") or price
            sku = p.get("sku", "").strip() or "Mặc định"
            valid = p.get("valid", True)

            diff_pct = 0
            if p.get("has_discount") and base > 0:
                diff_pct = round(((price - base) / base) * 100, 1)

            updated_list.append({
                "id": idx,
                "name": p.get("name", "Sản phẩm"),
                "sku": sku,
                "price": price,
                "base_price": base,
                "valid": valid,
                "diff_pct": diff_pct
            })
        self.products = updated_list
        if summary:
            self.summary = summary

    def set_cookie_status(self, is_valid: bool):
        self.cookie_status = "OK" if is_valid else "Hết hạn"

    def set_subscribers_count(self, count: int):
        self.subscribers_count = max(0, count)

    def set_next_check(self, dt: datetime):
        self.next_check_time = dt

    def increment_checks(self):
        self.total_checks += 1

    def get_countdown(self) -> int:
        if self.next_check_time:
            diff = int((self.next_check_time - datetime.now()).total_seconds())
            return max(0, diff)
        return 60

    def add_log(self, level: str, msg: str):
        """Thêm dòng log mới vào nhật ký hiển thị bên cột phải"""
        clean_msg = msg.strip().replace("\n", " ")
        if len(clean_msg) > 90:
            clean_msg = clean_msg[:87] + "..."

        now_str = datetime.now().strftime("%H:%M:%S")
        self.logs.append({
            "time": now_str,
            "level": level.upper(),
            "msg": clean_msg
        })
        if len(self.logs) > 50:
            self.logs.pop(0)

    def make_header(self) -> Panel:
        now = datetime.now()
        uptime = str(now - self.start_time).split(".")[0]
        countdown = self.get_countdown()

        table = Table.grid(expand=True)
        table.add_column(justify="left", ratio=3)
        table.add_column(justify="center", ratio=4)
        table.add_column(justify="right", ratio=3)

        cycle_badge = "[bold yellow]1m[/]" if now.minute <= 15 else "[bold yellow]5m[/]"
        left_text = Text.from_markup("⚡ [bold white]LAZADA BOT[/] [bold green]● LIVE[/]")
        center_text = Text.from_markup(f"Chu kỳ: {cycle_badge} | Kế tiếp: [bold cyan]{countdown}s[/]")
        right_text = Text.from_markup(f"Subs: [bold green]{self.subscribers_count}[/] | Uptime: [bold white]{uptime}[/]")

        table.add_row(left_text, center_text, right_text)
        return Panel(table, style="white on navy_blue", box=box.ROUNDED)

    def make_products_panel(self) -> Panel:
        """Cột trái: Danh sách sản phẩm, SKU và giá tinh gọn"""
        table = Table(
            expand=True,
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            row_styles=["none", "dim"]
        )
        table.add_column("#", width=2, justify="center")
        table.add_column("Sản phẩm", ratio=5)
        table.add_column("Giá", justify="right", width=9, no_wrap=True)
        table.add_column("Gốc", justify="right", width=9, no_wrap=True)
        table.add_column("+/-", justify="center", width=7, no_wrap=True)

        for p in self.products[:12]:
            name = p["name"][:30] + ("..." if len(p["name"]) > 30 else "")
            sku = p["sku"][:22]
            item_desc = f"[bold white]{name}[/]\n  [dim cyan]↳ {sku}[/]"

            if not p.get("valid", True):
                price_str = "[dim strike]N/A[/]"
                base_str = "[dim strike]N/A[/]"
                change_str = "[red]Hết[/]"
            else:
                price_str = f"[bold green]{p['price']:,.0f}₫[/]"
                if p["base_price"] and p["base_price"] > p["price"]:
                    base_str = f"[dim strike]{p['base_price']:,.0f}₫[/]"
                else:
                    base_str = "[dim]—[/]"

                diff = p.get("diff_pct", 0)
                if diff < 0:
                    change_str = f"[bold green]{diff}%[/]"
                elif diff > 0:
                    change_str = f"[bold red]+{diff}%[/]"
                else:
                    change_str = "[dim]—[/]"

            table.add_row(str(p["id"]), item_desc, price_str, base_str, change_str)

        total_str = self.summary.get("Total", "0₫")
        sub_str = self.summary.get("Subtotal")
        promo_str = self.summary.get("Promotion")

        summary_parts = []
        if sub_str:
            summary_parts.append(f"Tạm tính: {sub_str}")
        if promo_str:
            summary_parts.append(f"Giảm: {promo_str}")
        sub_details = f" [dim]• { ' • '.join(summary_parts) }[/]" if summary_parts else ""

        summary_text = f"Tổng: [bold green]{total_str}[/]{sub_details}"

        left_content = Table.grid(expand=True)
        left_content.add_row(table)
        left_content.add_row(Rule(style="dim"))
        left_content.add_row(Text.from_markup(summary_text))

        item_count = len(self.products)
        return Panel(
            left_content,
            title=f"[bold yellow]GIỎ HÀNG ({item_count})[/]",
            border_style="yellow",
            box=box.ROUNDED
        )

    def make_logs_panel(self) -> Panel:
        """Cột phải: Nhật ký hệ thống tinh gọn"""
        table = Table(
            expand=True,
            box=box.SIMPLE,
            header_style="bold cyan",
            show_header=False
        )
        table.add_column("Time", width=8, style="dim")
        table.add_column("Tag", width=5, justify="center")
        table.add_column("Message", ratio=1)

        level_styles = {
            "INFO": "[cyan]INFO[/]",
            "SUCCESS": "[bold green]OK[/]",
            "OK": "[bold green]OK[/]",
            "WARNING": "[bold yellow]WARN[/]",
            "WARN": "[bold yellow]WARN[/]",
            "ERROR": "[bold red]ERR[/]",
            "ALERT": "[bold red]ERR[/]"
        }

        for item in self.logs[-15:]:
            tag = level_styles.get(item["level"], item["level"][:4])
            msg = item["msg"]
            if item["level"] in ("ALERT", "ERROR"):
                msg = f"[bold red]{msg}[/]"
            elif item["level"] in ("OK", "SUCCESS"):
                msg = f"[green]{msg}[/]"

            table.add_row(item["time"], tag, msg)

        cookie_badge = "[bold green]OK[/]" if self.cookie_status == "OK" else "[bold red]Hết hạn[/]"
        stats_text = (
            f"Đã quét: [bold green]{self.total_checks}[/] | "
            f"Cookie: {cookie_badge}"
        )

        right_content = Table.grid(expand=True)
        right_content.add_row(table)
        right_content.add_row(Rule(style="dim"))
        right_content.add_row(Text.from_markup(stats_text))

        return Panel(
            right_content,
            title="[bold cyan]NHẬT KÝ HỆ THỐNG[/]",
            border_style="cyan",
            box=box.ROUNDED
        )

    def make_footer(self) -> Panel:
        text = Text.from_markup("[bold red]Ctrl+C[/] Dừng bot | [cyan]/cart[/] [cyan]/track[/] [cyan]/add[/] [cyan]/schedule[/]")
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


dashboard = HostDashboard()


class DashboardLogHandler(logging.Handler):
    """Handler chuyển hướng log từ Python logging vào Dashboard"""
    def emit(self, record):
        try:
            msg = self.format(record)
            if "httpx" in record.name and record.levelno < logging.WARNING:
                return
            dashboard.add_log(record.levelname, msg)
        except Exception:
            pass


async def run_dashboard_loop():
    """Vòng lặp cập nhật Live TUI trên terminal"""
    if not sys.stdout.isatty() or os.getenv("DISABLE_DASHBOARD") == "1":
        return

    with Live(
        dashboard.generate_layout(),
        console=dashboard.console,
        refresh_per_second=2,
        screen=True
    ) as live:
        dashboard.live = live
        dashboard.is_running = True
        try:
            while dashboard.is_running:
                live.update(dashboard.generate_layout())
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            dashboard.is_running = False
