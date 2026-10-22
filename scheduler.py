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
    - Quét liên tục 1 phút / lần (tính chẵn từ đầu mỗi phút)
    """
    interval_minutes = 1
    target = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    delay = (target - now).total_seconds()
    # Đảm bảo delay tối thiểu 2 giây để tránh lặp tức thì
    delay = max(delay, 2.0)
    return target, delay, False, interval_minutes


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

            mode_str = f"Quét liên tục ({interval_mins} phút/lần)"
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
    mode = "⚡ Siêu tốc (1 phút/lần)"
    subs = get_subscribers()
    auto_status = "🟢 Đang bật" if is_auto_track_enabled() else "🔴 Đang tắt"

    lines = [
        "⏰ <b>LỊCH TRÌNH THEO DÕI GIÁ TỰ ĐỘNG:</b>\n",
        f"• Chế độ tự động: <b>{auto_status}</b>",
        f"• Tần suất quét: <b>{mode}</b>",
        f"• Lần quét gần nhất: <i>{scheduler_state['last_check_time'] or 'Chưa có'}</i>",
        f"• Lần quét tiếp theo: <i>{scheduler_state['next_check_time'] or 'Đang tính toán...'}</i>",
        f"• Số người nhận thông báo: <b>{len(subs)}</b>\n",
        "📌 <b>Quy định chu kỳ quét:</b>",
        "• Bot tự động kiểm tra giỏ hàng <b>1 phút/lần</b> liên tục để phát hiện biến động giá và mã giảm giá ngay lập tức.",
    ]
    return "\n".join(lines)
