"""
CLI Logger & Internet Monitor Module
Giao diện dòng lệnh tinh gọn dạng log thông thường:
- Theo dõi kết nối Internet & đo latency (ms) thời gian thực.
- Mỗi lần quét giỏ hàng xuất ra đúng 1 dòng log tổng hợp (Thời gian | Internet Status | Giỏ hàng | Biến động | Lần quét kế tiếp).
"""

import os
import sys
import time
import socket
import logging
from datetime import datetime
from typing import Tuple, List, Dict, Any, Optional

from rich.console import Console

console = Console(legacy_windows=False, highlight=False)


def check_internet(timeout: float = 2.0) -> Tuple[bool, int]:
    """
    Kiểm tra kết nối Internet và đo latency (ms).
    Thực hiện TCP handshake tới 8.8.8.8:53 hoặc 1.1.1.1:53 (siêu nhanh, không tốn DNS lookup).
    """
    endpoints = [("8.8.8.8", 53), ("1.1.1.1", 53)]
    for host, port in endpoints:
        start = time.perf_counter()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.close()
            latency = round((time.perf_counter() - start) * 1000)
            return True, latency
        except Exception:
            continue
    return False, -1


def format_net_badge(is_online: bool, latency: int = 0) -> str:
    """Format nhãn trạng thái Internet hiển thị trên dòng log"""
    if is_online:
        return f"[bold green][NET: OK {latency}ms][/]"
    return "[bold red][NET: OFFLINE][/]"


def print_cli(msg: str):
    """In log ra màn hình console với hỗ trợ mã màu Rich"""
    try:
        console.print(msg)
    except Exception:
        # Fallback in plain text nếu terminal lỗi mã hóa
        clean = msg.replace("[bold green]", "").replace("[/]", "").replace("[bold red]", "")
        print(clean)


def log_check_result(
    check_num: int,
    status: str,
    products: Optional[List[Dict[str, Any]]] = None,
    summary: Optional[Dict[str, Any]] = None,
    changes: Optional[List[Dict[str, Any]]] = None,
    next_time: Optional[datetime] = None,
    interval_mins: int = 1,
    is_online: bool = True,
    latency: int = 0,
    error_msg: Optional[str] = None
):
    """
    In đúng 1 dòng log tinh gọn sau mỗi lượt quét giỏ hàng kèm trạng thái Internet:
    Ví dụ:
    [17:25:00] [NET: OK 35ms] Quét giỏ #1: 19 SKU | Tổng: 1,642,000₫ | Giá không đổi | Kế tiếp: 17:26:00 (1m)
    """
    now_str = datetime.now().strftime("%H:%M:%S")
    net_badge = format_net_badge(is_online, latency)

    if not is_online:
        print_cli(f"[dim][{now_str}][/] {net_badge} [bold red]Quét giỏ #{check_num}: Mất kết nối Internet! Bỏ qua lượt quét.[/]")
        return

    if status == "need_login":
        print_cli(f"[dim][{now_str}][/] {net_badge} [bold red]Quét giỏ #{check_num}: Cookie hết hạn! Vui lòng nạp lại qua /cookie[/]")
        return

    if status == "empty":
        print_cli(f"[dim][{now_str}][/] {net_badge} [yellow]Quét giỏ #{check_num}: Giỏ hàng trống (0 SKU)[/]")
        return

    if status != "ok":
        err = error_msg or "Lỗi không xác định"
        print_cli(f"[dim][{now_str}][/] {net_badge} [bold red]Quét giỏ #{check_num}: Lỗi - {err}[/]")
        return

    products = products or []
    summary = summary or {}
    changes = changes or []
    sku_count = len(products)
    total_str = summary.get("Total", "0₫")
    next_str = next_time.strftime("%H:%M:%S") if next_time else "--:--:--"

    if changes:
        change_desc = f"[bold red]🔥 PHÁT HIỆN {len(changes)} BIẾN ĐỘNG GIÁ![/]"
    else:
        change_desc = "[green]Giá không đổi[/]"

    line = (
        f"[dim][{now_str}][/] {net_badge} "
        f"[bold cyan]Quét giỏ #{check_num}:[/] "
        f"[bold white]{sku_count} SKU[/] | "
        f"Tổng: [bold green]{total_str}[/] | "
        f"{change_desc} | "
        f"Kế tiếp: [dim]{next_str} ({interval_mins}m)[/]"
    )
    print_cli(line)


class HostDashboard:
    """Class giữ trạng thái giỏ hàng và số liệu thống kê cơ bản"""
    def __init__(self):
        self.products: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}
        self.total_checks: int = 0
        self.subscribers_count: int = 0
        self.next_check_time: Optional[datetime] = None
        self.cookie_status: str = "OK"

    def update_cart(self, products: List[Dict[str, Any]], summary: Dict[str, Any]):
        self.products = products
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


dashboard = HostDashboard()


class DashboardLogHandler(logging.Handler):
    """Handler đơn giản hóa: lọc bớt log rác và in thẳng ra terminal theo định dạng chuẩn"""
    def emit(self, record):
        try:
            if "httpx" in record.name and record.levelno < logging.WARNING:
                return
            if "telegram" in record.name and record.levelno < logging.WARNING:
                return
            msg = self.format(record)
            now_str = datetime.now().strftime("%H:%M:%S")
            level = record.levelname
            style = "white"
            if level == "WARNING": style = "yellow"
            elif level == "ERROR": style = "bold red"
            elif level == "INFO": style = "cyan"
            print_cli(f"[dim][{now_str}][/] [{style}]{level}[/] {msg}")
        except Exception:
            pass


async def run_dashboard_loop():
    """Tương thích ngược: không cần chạy TUI chiếm màn hình nữa"""
    pass
