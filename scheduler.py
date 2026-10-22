"""
Background Scheduler for Lazada Price Tracker
Lịch trình tự động kiểm tra giỏ hàng:
- Quét liên tục: 1 phút / lần (tính chẵn từ đầu phút: :00, :01, :02, ...)
- Tự động phát hiện biến động giá của tất cả sản phẩm & phân loại và gửi kèm link mua hàng qua Telegram
- Tự động phát hiện và gửi cảnh báo Cookie hết hạn
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from subscriber_manager import get_subscribers, is_auto_track_enabled
from price_tracker import track_prices, format_changes_alert
from dashboard import dashboard

logger = logging.getLogger(__name__)

# Các mốc phút kiểm tra trong mỗi giờ:
# - 15 phút đầu giờ (:00 đến :15): quét 1 phút / lần (lần cuối ở phút 15)
# - Sau đó cho đến hết giờ (:20 đến :55): quét 5 phút / lần
SCHEDULED_MINUTES = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    20, 25, 30, 35, 40, 45, 50, 55
]

# Biến lưu trạng thái scheduler
scheduler_state = {
    "is_running": False,
    "last_check_time": None,
    "next_check_time": None,
    "current_mode": "Chưa chạy",
    "cookie_alert_sent": False,
    "last_error": None
}


def calculate_next_run(now: datetime) -> Tuple[datetime, float, bool, int]:
    """
    Tính thời điểm chạy tiếp theo:
    - Đầu mỗi giờ (:00 đến :15): quét 1 phút / lần (phút 15 là lần cuối của chu kỳ 1p)
    - Sau phút 15 đến hết giờ (:20, :25, ... :55): quét 5 phút / lần
    """
    target = None
    for m in SCHEDULED_MINUTES:
        candidate = now.replace(minute=m, second=0, microsecond=0)
        if (candidate - now).total_seconds() >= 2.0:
            target = candidate
            break

    if target is None:
        target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    delay = max((target - now).total_seconds(), 2.0)
    is_peak = (target.minute <= 15 and target.minute != 0) or (target.minute == 0)
    interval_minutes = 1 if is_peak else 5
    return target, delay, is_peak, interval_minutes


async def broadcast_message(bot, text: str) -> int:
    """Gửi thông báo tới tất cả người dùng đã đăng ký"""
    subscribers = get_subscribers()
    if not subscribers or not text:
        return 0

    success_count = 0
    for chat_id in subscribers:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            success_count += 1
        except Exception as e:
            logger.warning(f"Không thể gửi thông báo tới chat_id {chat_id}: {e}")

    return success_count


async def run_single_check(bot) -> None:
    """Thực hiện một lần quét giỏ hàng và gửi cảnh báo nếu có thay đổi hoặc cookie hết hạn"""
    now = datetime.now()
    scheduler_state["last_check_time"] = now.strftime("%H:%M:%S %d/%m/%Y")
    logger.info(f"[*] Bắt đầu quét giỏ hàng tự động lúc {scheduler_state['last_check_time']}...")
    dashboard.increment_checks()
    dashboard.set_subscribers_count(len(get_subscribers()))

    try:
        result = await asyncio.to_thread(track_prices, True)
    except Exception as e:
        logger.error(f"Lỗi khi chạy track_prices: {e}", exc_info=True)
        return

    status = result.get("status")

    # 1. Xử lý trường hợp Cookie hết hạn
    if status == "need_login":
        dashboard.set_cookie_status(False)
        if not scheduler_state["cookie_alert_sent"]:
            alert_text = (
                "🚨 <b>CẢNH BÁO: COOKIE LAZADA ĐÃ HẾT HẠN!</b>\n\n"
                "Bot không thể tiếp tục quét giỏ hàng vì phiên đăng nhập đã hết hạn.\n"
                "👉 <b>Cách khắc phục:</b> Hãy copy cookie mới từ trình duyệt và gửi cho bot:\n"
                "<code>/cookie &lt;dán_cookie_mới_vào_đây&gt;</code>"
            )
            logger.warning("Cookie đã hết hạn, đang gửi cảnh báo tới người dùng...")
            await broadcast_message(bot, alert_text)
            scheduler_state["cookie_alert_sent"] = True
        return

    # Nếu thành công, reset cờ cảnh báo cookie
    if status == "ok":
        dashboard.set_cookie_status(True)
        scheduler_state["cookie_alert_sent"] = False

        products = result.get("products", [])
        summary = result.get("summary", {})
        if products:
            dashboard.update_cart(products, summary)

        changes = result.get("changes", [])
        total_change = result.get("total_change")

        # 2. Xử lý trường hợp có biến động giá sản phẩm hoặc phân loại
        if changes or total_change:
            alert_msg = format_changes_alert(changes, total_change)
            if alert_msg:
                logger.info(f"Phát hiện {len(changes)} thay đổi giá! Đang gửi cảnh báo...")
                await broadcast_message(bot, alert_msg)
        else:
            logger.info("Quét hoàn tất: Không có biến động giá.")


async def start_scheduler_loop(bot) -> None:
    """Vòng lặp tự động chạy kiểm tra theo lịch"""
    scheduler_state["is_running"] = True
    logger.info("🚀 Scheduler tự động theo dõi giá đã khởi động.")

    while True:
        try:
            now = datetime.now()
            target_time, delay_seconds, is_peak, interval_mins = calculate_next_run(now)
            dashboard.set_next_check(target_time)

            phase_label = "Đầu giờ (:00-:15)" if is_peak else "Sau phút 15 (:20-:55)"
            mode_str = f"{phase_label} - {interval_mins}p/lần"
            scheduler_state["current_mode"] = mode_str
            scheduler_state["next_check_time"] = target_time.strftime("%H:%M:%S %d/%m/%Y")

            logger.info(f"Lần check tiếp theo lúc {target_time.strftime('%H:%M:%S')} (sau {int(delay_seconds)}s) [{mode_str}]")

            # Chờ đến thời điểm kế tiếp
            await asyncio.sleep(delay_seconds)

            # Kiểm tra nếu tính năng auto track đang được bật
            if is_auto_track_enabled():
                await run_single_check(bot)

        except asyncio.CancelledError:
            scheduler_state["is_running"] = False
            logger.info("Scheduler đã dừng theo yêu cầu.")
            break
        except Exception as e:
            scheduler_state["last_error"] = str(e)
            logger.error(f"Lỗi trong vòng lặp scheduler: {e}", exc_info=True)
            await asyncio.sleep(15)


def get_status_info() -> str:
    """Tạo báo cáo tình trạng hoạt động của scheduler"""
    now = datetime.now()
    subs = get_subscribers()
    auto_status = "🟢 Đang bật" if is_auto_track_enabled() else "🔴 Đang tắt"
    current_phase = "⚡ Đầu giờ (1 phút/lần)" if now.minute <= 15 else "⏳ Sau phút 15 (5 phút/lần)"

    lines = [
        "⏰ <b>LỊCH TRÌNH THEO DÕI GIÁ TỰ ĐỘNG:</b>\n",
        f"• Chế độ tự động: <b>{auto_status}</b>",
        f"• Giai đoạn hiện tại: <b>{current_phase}</b>",
        f"• Lần quét gần nhất: <i>{scheduler_state['last_check_time'] or 'Chưa có'}</i>",
        f"• Lần quét tiếp theo: <i>{scheduler_state['next_check_time'] or 'Đang tính toán...'}</i>",
        f"• Số người nhận thông báo: <b>{len(subs)}</b>\n",
        "📌 <b>Quy định chu kỳ quét:</b>",
        "• <b>15 phút đầu mỗi giờ (:00 - :15):</b> Quét <b>1 phút/lần</b> (phút 15 là lần quét 1p cuối cùng).",
        "• <b>Sau phút 15 đến hết giờ (:20 - :55):</b> Quét <b>5 phút/lần</b> cho đến khi sang giờ mới.",
    ]
    return "\n".join(lines)
