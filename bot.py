"""
Father Bot - Telegram Bot + Lazada Cart Price Tracker (Anti-Detect + Headless)
Hỗ trợ:
- Tự động theo dõi giá theo lịch:
  + Khung giờ cao điểm (0h, 9h, 12h, 15h, 18h, 21h): 2 phút/lần
  + Khung giờ thường: 15 phút/lần (tính từ đầu giờ: :00, :15, :30, :45)
- Theo dõi độc lập từng sản phẩm & từng phân loại (SKU)
- Tự động gửi cảnh báo khi giá tăng/giảm hoặc thay đổi tồn kho
- Tự động gửi cảnh báo khi Cookie hết hạn
- Tuyệt đối không bấm vào trang thanh toán (chỉ thao tác trên giỏ hàng)
"""

import asyncio
import logging
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from cookie_manager import (
    parse_cookie_input,
    save_cookies_list,
    load_saved_cookies,
    prompt_interactive_cookie,
)
from price_tracker import (
    scrape_cart,
    track_prices,
    get_price_summary,
    format_cart_message,
    format_cart_messages,
    format_changes_alert,
)
from subscriber_manager import (
    add_subscriber,
    remove_subscriber,
    get_subscribers,
    is_auto_track_enabled,
    set_auto_track_enabled,
)
from scheduler import start_scheduler_loop, get_status_info, run_single_check

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def auto_register_user(update: Update) -> None:
    """Tự động đăng ký chat_id của người dùng để nhận cảnh báo biến động giá"""
    if update.effective_chat:
        add_subscriber(update.effective_chat.id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    user = update.effective_user
    msg = (
        f"Xin chào <b>{user.first_name}</b>! 👋\n\n"
        f"🤖 Tôi là <b>Father Bot</b> - Công cụ theo dõi giá giỏ hàng Lazada tự động (Anti-detect).\n\n"
        f"🎯 <b>Tính năng nổi bật:</b>\n"
        f"• Đăng nhập bằng Cookie (Không mở trình duyệt)\n"
        f"• Tự động tick <b>Chọn tất cả</b> để đọc giá sau Voucher & Khuyến mãi\n"
        f"• Theo dõi độc lập <b>tất cả phân loại (SKU)</b> của từng sản phẩm\n"
        f"• Lịch quét thông minh: <b>5 phút/lần</b> (Khung 0h, 9h, 12h, 15h, 18h, 21h: <b>2 phút/lần</b>)\n"
        f"• Tự động gửi thông báo khi <b>Biến động giá</b> hoặc <b>Cookie hết hạn</b>\n"
        f"• An toàn tuyệt đối: Không bao giờ bấm vào trang thanh toán\n\n"
        f"🔑 <b>Cách nạp Cookie Lazada:</b>\n"
        f"1. <b>Dán trực tiếp:</b> Copy JSON từ Cookie-Editor rồi dán thẳng vào tin nhắn này.\n"
        f"2. <b>Gửi file:</b> Kéo thả hoặc gửi file <code>cookie.json</code>.\n"
        f"3. <b>Dùng lệnh:</b> <code>/cookie &lt;dán JSON vào đây&gt;</code>\n\n"
        f"👉 Gõ /help để xem toàn bộ danh sách lệnh."
    )
    if update.effective_message:
        await update.effective_message.reply_html(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    text = (
        "📖 <b>DANH SÁCH LỆNH CỦA BOT:</b>\n\n"
        "🛒 <b>Quản lý Giỏ Hàng & Giá:</b>\n"
        "• <code>/cart</code> : Quét & hiển thị toàn bộ giỏ hàng với Giá Cuối Cùng\n"
        "• <code>/track</code> : Kiểm tra biến động giá ngay lập tức\n"
        "• <code>/prices</code> : Xem danh sách giá các mặt hàng đã lưu\n\n"
        "⏰ <b>Lịch Trình Tự Động:</b>\n"
        "• <code>/schedule</code> (hoặc <code>/auto</code>) : Xem tình trạng lịch quét tự động\n"
        "• <code>/check_now</code> : Kích hoạt 1 lượt quét giỏ hàng ngay\n"
        "• <code>/auto_on</code> : Bật chế độ tự động quét theo lịch\n"
        "• <code>/auto_off</code> : Tắt chế độ tự động quét\n"
        "• <code>/sub</code> : Đăng ký nhận thông báo cảnh báo giá\n"
        "• <code>/unsub</code> : Hủy nhận thông báo tự động\n\n"
        "🔑 <b>Cookie Lazada:</b>\n"
        "• <code>/cookie &lt;nội_dung&gt;</code> : Nạp cookie trực tiếp\n"
        "• <code>/cookie_status</code> : Kiểm tra tình trạng cookie hiện tại\n\n"
        "ℹ️ <code>/ping</code> : Kiểm tra bot còn sống không"
    )
    if update.effective_message:
        await update.effective_message.reply_html(text)


async def cookie_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    full_text = msg.text or ""
    # Cắt bỏ /cookie hoặc /cookie@botname
    raw_input = re.sub(r'^/cookie(@\w+)?\s*', '', full_text, flags=re.IGNORECASE).strip()
    if not raw_input and context.args:
        raw_input = " ".join(context.args).strip()

    if not raw_input:
        help_guide = (
            "📌 <b>Cách nạp cookie Lazada:</b>\n\n"
            "1. <b>Dán trực tiếp</b>: Bạn chỉ cần copy mảng JSON từ Cookie-Editor rồi <b>dán thẳng vào chat</b> bot sẽ tự nhận diện!\n"
            "2. <b>Dùng lệnh /cookie</b>: <code>/cookie &lt;dán JSON vào đây&gt;</code>\n"
            "3. <b>Gửi file</b>: Kéo thả file <code>cookie.json</code> vào chat.\n\n"
            "<i>(Nếu chạy trên Termux, bạn cũng có thể dán trực tiếp trong terminal mỗi khi khởi động bot)</i>"
        )
        await msg.reply_html(help_guide)
        return

    cookies = parse_cookie_input(raw_input)
    if not cookies:
        await msg.reply_text("❌ Không thể nhận diện định dạng cookie. Vui lòng kiểm tra lại chuỗi copy.")
        return

    count = save_cookies_list(cookies)
    await msg.reply_html(
        f"✅ <b>Đã nạp thành công {count} cookies!</b>\n"
        f"👉 Hãy gõ <code>/cart</code> để kiểm tra giỏ hàng và giá thực tế ngay!"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý khi người dùng gửi file cookie (.json / .txt / document bất kỳ) đính kèm qua Telegram"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg or not msg.document:
        return

    doc = msg.document
    file_name = doc.file_name or "cookie_file"

    status_msg = await msg.reply_text("📥 Đang nhận và giải mã file cookie...")
    try:
        tg_file = await doc.get_file()
        file_bytes = await tg_file.download_as_bytearray()
        content = file_bytes.decode("utf-8", errors="replace")

        cookies = parse_cookie_input(content)
        if not cookies:
            await status_msg.edit_text("❌ Không tìm thấy cookie Lazada hợp lệ trong file. Vui lòng kiểm tra định dạng.")
            return

        count = save_cookies_list(cookies)
        await status_msg.edit_text(
            f"✅ <b>Đã nạp thành công {count} cookies từ file {file_name}!</b>\n"
            f"👉 Hãy gõ <code>/cart</code> để kiểm tra giỏ hàng ngay!",
            parse_mode="HTML"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Lỗi khi đọc file: {e}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tự động phát hiện khi người dùng paste chuỗi JSON cookie trực tiếp mà không cần gõ /cookie"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg or not msg.text:
        return

    text = msg.text.strip()
    # Nhận diện nếu tin nhắn chứa JSON cookie hoặc chuỗi cookie Lazada
    has_cookie_markers = (
        ("[" in text and "]" in text) or
        ("{" in text and "}" in text) or
        "lzd_sid" in text or
        "t_uid" in text or
        "sgcookie" in text or
        "t_sid=" in text
    )
    if has_cookie_markers:
        cookies = parse_cookie_input(text)
        if cookies and len(cookies) > 0:
            count = save_cookies_list(cookies)
            await msg.reply_html(
                f"✅ <b>Đã tự động nhận diện và nạp {count} cookies!</b>\n"
                f"👉 Hãy gõ <code>/cart</code> để kiểm tra giỏ hàng ngay!"
            )
            return


async def cookie_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    cookies = load_saved_cookies()
    if not cookies:
        await msg.reply_text("⚠️ Hiện chưa có cookie nào được lưu. Dùng /cookie để nạp.")
        return

    names = [c.get("name") for c in cookies]
    has_auth = any(n in names for n in ["t_uid", "lzd_sid", "epssw", "t_sid"])
    status_str = "🟢 Đã xác thực tài khoản" if has_auth else "🟡 Cookie khách"

    text = (
        f"🍪 <b>Trạng thái Cookie:</b>\n"
        f"• Tổng số cookie: {len(cookies)}\n"
        f"• Trạng thái: {status_str}\n"
        f"• Session tokens: {', '.join([n for n in ['t_uid', 'lzd_sid', 'epssw'] if n in names]) or 'Không'}"
    )
    await msg.reply_html(text)


async def cart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    status_msg = await msg.reply_text("⏳ Đang quét giỏ hàng, chọn tất cả sản phẩm và đọc Giá Cuối Cùng...")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: scrape_cart(headless=True))

    if result["status"] == "need_login":
        await status_msg.edit_text(
            f"❌ {result['message']}\n\n"
            f"👉 Dùng lệnh: <code>/cookie &lt;nội_dung&gt;</code> để nạp cookie mới.",
            parse_mode="HTML"
        )
        return

    if result["status"] == "empty":
        await status_msg.edit_text("🛒 Giỏ hàng Lazada của bạn hiện đang trống!")
        return

    if result["status"] != "ok":
        await status_msg.edit_text(f"❌ {result['message']}")
        return

    products = result["products"]
    summary = result.get("summary", {})
    messages = format_cart_messages(products, summary)

    if messages:
        await status_msg.edit_text(messages[0], parse_mode="HTML")
        for extra in messages[1:]:
            await msg.reply_html(extra)


async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    status_msg = await msg.reply_text("🔍 Đang kiểm tra biến động giá thực tế của tất cả phân loại...")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: track_prices(headless=True))

    if result["status"] != "ok":
        await status_msg.edit_text(f"❌ {result['message']}")
        return

    total = result["total_products"]
    changes = result["changes"]
    total_change = result.get("total_change")
    summary = result.get("summary", {})

    summary_header = f"📊 Đã chọn & kiểm tra <b>{total}</b> phân loại sản phẩm trong giỏ.\n"
    if summary and "Total" in summary:
        summary_header += f"💵 <b>Giá cuối cùng hiện tại:</b> <code>{summary['Total']}</code>\n\n"
    else:
        summary_header += "\n"

    if changes or total_change:
        changes_msg = format_changes_alert(changes, total_change)
    else:
        changes_msg = "✅ Tất cả sản phẩm & phân loại vẫn giữ nguyên giá (không đổi)."

    full_text = summary_header + changes_msg
    if len(full_text) > 4000:
        full_text = full_text[:4000] + "\n\n<i>... (cắt ngắn)</i>"

    await status_msg.edit_text(full_text, parse_mode="HTML")


async def prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return
    text = get_price_summary()
    if len(text) > 4000:
        text = text[:4000] + "\n\n<i>... (cắt ngắn)</i>"
    await msg.reply_html(text)


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return
    status_text = get_status_info()
    await msg.reply_html(status_text)


async def auto_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    set_auto_track_enabled(True)
    if update.effective_message:
        await update.effective_message.reply_text("🟢 Đã BẬT chế độ tự động kiểm tra giỏ hàng theo lịch!")


async def auto_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    set_auto_track_enabled(False)
    if update.effective_message:
        await update.effective_message.reply_text("🔴 Đã TẮT chế độ tự động kiểm tra giỏ hàng theo lịch.")


async def sub_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        add_subscriber(chat_id)
        if update.effective_message:
            await update.effective_message.reply_text("✅ Bạn đã đăng ký nhận thông báo biến động giá tự động!")


async def unsub_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        remove_subscriber(chat_id)
        if update.effective_message:
            await update.effective_message.reply_text("❌ Bạn đã hủy nhận thông báo tự động.")


async def check_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    msg = update.effective_message
    if msg:
        await msg.reply_text("⚡ Đang kích hoạt 1 lượt quét ngay lập tức...")
    await run_single_check(context.bot)
    if msg:
        await msg.reply_text("✅ Đã hoàn tất lượt quét kiểm tra!")


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("🏓 Pong! Father Bot đang hoạt động bình thường.")


async def post_init(application: Application) -> None:
    """Khởi động tác vụ background scheduler ngay khi bot chạy"""
    asyncio.create_task(start_scheduler_loop(application.bot))
    logger.info("[OK] Background scheduler task đã được khởi tạo trong asyncio event loop.")


def main() -> None:
    # 1. Tùy chọn nạp JSON Cookie khi khởi động (Hữu ích khi chạy trên Termux / Console)
    prompt_interactive_cookie()

    # Khởi tạo event loop cho MainThread (sửa lỗi RuntimeError trên Python 3.12, 3.13 và 3.14)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        print("[!] Lỗi: Chưa có TELEGRAM_BOT_TOKEN trong file .env")
        return

    print("[*] Khởi động Father Bot Telegram + Auto Scheduler...")
    app = Application.builder().token(token).post_init(post_init).build()

    # Handlers cơ bản
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping_command))

    # Handlers giỏ hàng & giá
    app.add_handler(CommandHandler("cart", cart_command))
    app.add_handler(CommandHandler("track", track_command))
    app.add_handler(CommandHandler("prices", prices_command))

    # Handlers lịch trình tự động
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("auto", schedule_command))
    app.add_handler(CommandHandler("auto_on", auto_on_command))
    app.add_handler(CommandHandler("auto_off", auto_off_command))
    app.add_handler(CommandHandler("sub", sub_command))
    app.add_handler(CommandHandler("unsub", unsub_command))
    app.add_handler(CommandHandler("check_now", check_now_command))

    # Handlers Cookie
    app.add_handler(CommandHandler("cookie", cookie_command))
    app.add_handler(CommandHandler("cookie_status", cookie_status_command))

    # Tự động nạp khi gửi file cookie (.json / .txt) hoặc paste JSON trực tiếp
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("[OK] Bot đã sẵn sàng nhận lệnh từ Telegram.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
