"""
Father Bot - Host Terminal CLI Dashboard (DEMO)
Chạy bản demo độc lập để trải nghiệm giao diện TUI 2 cột tinh gọn:
python demo_dashboard.py
"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import os
import time
import random
from datetime import datetime, timedelta

from rich.live import Live
from dashboard import dashboard

def run_demo():
    # Nạp một số log mẫu ban đầu nếu dashboard chưa có log
    if not dashboard.logs:
        demo_logs = [
            ("INFO", "Hệ thống Lazada Bot khởi động trên host."),
            ("OK", "Đã nạp 15 cookies Lazada với đầy đủ phiên auth."),
            ("OK", "Stealth Driver sẵn sàng (CDP Bypass)."),
            ("INFO", "Scheduler khởi động: Lịch quét tự động 1m."),
            ("OK", "Đã kết nối Telegram Bot thành công."),
            ("INFO", "Bắt đầu quét giỏ hàng tự động..."),
            ("OK", "Đã chọn tất cả sản phẩm trong giỏ."),
            ("WARN", "Phát hiện biến động giá: Giảm 15%!"),
            ("OK", "Đã gửi thông báo biến động qua Telegram.")
        ]
        for lvl, msg in demo_logs:
            dashboard.add_log(lvl, msg)

    dashboard.set_subscribers_count(1)
    dashboard.set_next_check(datetime.now() + timedelta(seconds=45))

    console = dashboard.console
    with Live(dashboard.generate_layout(), console=console, refresh_per_second=2, screen=True) as live:
        dashboard.live = live
        dashboard.is_running = True
        step = 0
        try:
            while dashboard.is_running:
                step += 1
                live.update(dashboard.generate_layout())
                time.sleep(1)

                # Cứ 15s mô phỏng 1 sự kiện ngẫu nhiên trong demo
                if step % 15 == 0:
                    events = [
                        ("INFO", "Scheduler kích hoạt lượt quét tự động 1m..."),
                        ("OK", "Chọn tất cả sản phẩm và đọc giá khuyến mãi thành công."),
                        ("INFO", "Kiểm tra 19 SKU trong giỏ hàng hoàn tất."),
                        ("WARN", "Phát hiện Flash Sale Lazada cho 1 SKU!"),
                        ("OK", "Cảnh báo biến động giá đã gửi tới 1 subscribers.")
                    ]
                    lvl, txt = random.choice(events)
                    dashboard.add_log(lvl, txt)
                    dashboard.increment_checks()
                    dashboard.set_next_check(datetime.now() + timedelta(seconds=60))

        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    run_demo()
