"""
Father Bot - Host Terminal CLI (DEMO)
Chạy bản demo độc lập để trải nghiệm giao diện CLI Log tinh gọn kèm theo dõi kết nối Internet:
python demo_dashboard.py
"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import time
from datetime import datetime, timedelta

from dashboard import check_internet, format_net_badge, print_cli, log_check_result


def run_demo():
    print_cli("==================================================================")
    print_cli("🤖 [bold white]FATHER BOT - LAZADA PRICE TRACKER (CLI LOG MODE)[/]")
    print_cli("==================================================================")

    is_online, latency = check_internet()
    badge = format_net_badge(is_online, latency)
    print_cli(f"{badge} [bold green]Hệ thống khởi động thành công.[/] Lịch: 1p/lần (:00-:15) & 5p/lần (:20-:55)")
    print_cli(f"{badge} [bold green]Đã nạp 15 cookies Lazada.[/] Phiên auth đầy đủ.")
    print_cli(f"{badge} [bold green]Telegram Bot sẵn sàng nhận lệnh[/] (1 subscribers)")
    print_cli("------------------------------------------------------------------")

    sample_products = [
        {"name": "SmartDevil Cường lực", "sku": "2 miếng", "price": 117000},
        {"name": "Cáp sạc Ugreen Type-C", "sku": "Đen 20cm", "price": 60000},
        {"name": "Chuột không dây Logitech", "sku": "Màu xám", "price": 250000},
    ]
    summary = {"Total": "427,000₫"}

    # Mô phỏng các lượt quét (có đo kết nối Internet thực tế)
    for check_num in range(1, 5):
        is_online, latency = check_internet()
        next_time = datetime.now() + timedelta(minutes=1)

        # Mô phỏng lượt check thứ 3 có biến động giá
        changes = []
        if check_num == 3:
            changes = [{"name": "SmartDevil Cường lực", "diff": -15000, "direction": "GIẢM"}]
            summary = {"Total": "412,000₫"}

        log_check_result(
            check_num=check_num,
            status="ok",
            products=sample_products,
            summary=summary,
            changes=changes,
            next_time=next_time,
            interval_mins=1,
            is_online=is_online,
            latency=latency
        )
        time.sleep(1.5)

    # Mô phỏng tình huống ngắt mạng
    log_check_result(
        check_num=5,
        status="offline",
        is_online=False,
        latency=-1
    )

    print_cli("------------------------------------------------------------------")
    print_cli("[dim]Hoàn tất demo. Chạy 'python bot.py' để vận hành bot chính thức.[/]")


if __name__ == "__main__":
    run_demo()
