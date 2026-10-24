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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from cart_adder import extract_lazada_url, fetch_product_details, add_sku_to_cart
from anti_detect import close_shared_driver

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
    load_price_history,
    format_cart_message,
    format_cart_messages,
    format_changes_alert,
)
from target_price_manager import (
    parse_user_price,
    set_target_price,
    remove_target_price,
    clear_all_target_prices,
    get_all_target_prices,
    get_target_price,
    find_product_by_query,
)
from subscriber_manager import (
    add_subscriber,
    remove_subscriber,
    get_subscribers,
    is_auto_track_enabled,
    set_auto_track_enabled,
)
from scheduler import start_scheduler_loop, get_status_info, run_single_check
from dashboard import (
    dashboard,
    check_internet,
    format_net_badge,
    print_cli,
    log_check_result,
)

load_dotenv()

logging.basicConfig(
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
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
        f"• Tần suất quét: <b>1 phút/lần</b> (15p đầu giờ) & <b>5 phút/lần</b> (đến hết giờ)\n"
        f"• <b>Đặt giá mục tiêu:</b> Cài mức giá mong muốn (<code>/setprice</code>), bot CHỈ báo khi giá giảm xuống ≤ mức này!\n"
        f"• Tự động gửi cảnh báo kèm <b>thông tin phân loại & link mua hàng</b>\n"
        f"• <b>Thêm vào giỏ hàng bằng link</b>: Dán link sản phẩm là có nút chọn phân loại ngay\n"
        f"• An toàn tuyệt đối: Không bao giờ bấm vào trang thanh toán\n\n"
        f"🔗 <b>Thêm sản phẩm mới vào giỏ:</b>\n"
        f"Chỉ cần gửi link Lazada (hoặc gõ <code>/add &lt;link&gt;</code>) vào đây!\n\n"
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
        "• <code>/prices</code> : Xem danh sách giá các mặt hàng đã lưu\n"
        "• <code>/add &lt;link&gt;</code> : Thêm sản phẩm vào giỏ (chọn phân loại qua nút bấm)\n\n"
        "🎯 <b>Mức Giá Mục Tiêu (Target Price):</b>\n"
        "• <code>/setprice &lt;stt&gt; &lt;giá&gt;</code> : Chỉ báo động khi giá giảm xuống ≤ mức này (VD: <code>/setprice 1 100k</code>)\n"
        "• <code>/delprice &lt;stt&gt;</code> : Xóa mức giá mục tiêu (sẽ báo mọi biến động)\n"
        "• <code>/targets</code> : Xem danh sách sản phẩm đang cài giá mục tiêu\n\n"
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
    close_shared_driver()
    dashboard.set_cookie_status(True)
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
        close_shared_driver()
        dashboard.set_cookie_status(True)
        await status_msg.edit_text(
            f"✅ <b>Đã nạp thành công {count} cookies từ file {file_name}!</b>\n"
            f"👉 Hãy gõ <code>/cart</code> để kiểm tra giỏ hàng ngay!",
            parse_mode="HTML"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Lỗi khi đọc file: {e}")


async def handle_lazada_product_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    """Xử lý link sản phẩm Lazada: lấy thông tin chi tiết và hiển thị nút chọn phân loại"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    status_msg = await msg.reply_text("🔍 Đang đọc thông tin sản phẩm và các phân loại từ Lazada...")

    loop = asyncio.get_running_loop()
    details = await loop.run_in_executor(None, lambda: fetch_product_details(url, headless=True))

    if details.get("status") != "ok":
        err_msg = details.get("message", "Không thể lấy thông tin sản phẩm từ link này.")
        await status_msg.edit_text(f"❌ {err_msg}")
        return

    title = details.get("title") or "Sản phẩm Lazada"
    price = details.get("price") or "N/A"
    orig_price = details.get("original_price")
    variations = details.get("variations") or []
    prod_url = details.get("url") or url

    # Lưu thông tin phiên chọn vào context.user_data
    context.user_data["add_cart_session"] = {
        "url": prod_url,
        "title": title,
        "price": price,
        "variations": variations
    }

    price_line = f"💰 <b>Giá:</b> <code>{price}</code>"
    if orig_price and orig_price != price:
        price_line += f" <s>{orig_price}</s>"

    header_text = (
        f"🛍️ <b>THÔNG TIN SẢN PHẨM:</b>\n\n"
        f"📦 <b>{title}</b>\n"
        f"{price_line}\n"
    )

    if variations:
        guide_text = header_text + f"\n👉 <b>Vui lòng bấm chọn Phân loại (SKU) để thêm vào giỏ:</b>"
        keyboard = []
        row = []
        for idx, v in enumerate(variations):
            btn_text = v["name"]
            if v.get("selected"):
                btn_text = f"🔘 {btn_text}"
            row.append(InlineKeyboardButton(text=btn_text, callback_data=f"addcart:{idx}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton(text="❌ Hủy bỏ", callback_data="addcart:cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text(guide_text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        guide_text = header_text + f"\n<i>(Sản phẩm này có 1 phân loại mặc định)</i>"
        keyboard = [
            [InlineKeyboardButton(text="🛒 Thêm vào giỏ hàng ngay", callback_data="addcart:default")],
            [InlineKeyboardButton(text="❌ Hủy bỏ", callback_data="addcart:cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text(guide_text, parse_mode="HTML", reply_markup=reply_markup)


async def handle_add_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý khi người dùng bấm nút chọn phân loại để thêm vào giỏ"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    if not data.startswith("addcart:"):
        return

    action = data.split(":", 1)[1]
    if action == "cancel":
        await query.edit_message_text("❌ Đã hủy thao tác thêm vào giỏ hàng.")
        context.user_data.pop("add_cart_session", None)
        return

    session = context.user_data.get("add_cart_session")
    if not session:
        await query.edit_message_text("⚠️ Phiên chọn sản phẩm đã hết hạn. Vui lòng gửi lại link sản phẩm.")
        return

    url = session.get("url")
    title = session.get("title")
    price = session.get("price")
    variations = session.get("variations") or []

    sku_name = None
    if action.isdigit():
        idx = int(action)
        if 0 <= idx < len(variations):
            sku_name = variations[idx]["name"]
    elif action == "default":
        sku_name = None

    sku_display = f" <i>[Phân loại: <b>{sku_name}</b>]</i>" if sku_name else ""
    await query.edit_message_text(f"⏳ Đang thêm{sku_display} vào giỏ hàng Lazada của bạn...", parse_mode="HTML")

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, lambda: add_sku_to_cart(url, sku_name, headless=True))

    if res.get("status") == "ok":
        success_text = (
            f"✅ <b>ĐÃ THÊM THÀNH CÔNG VÀO GIỎ HÀNG LAZADA!</b> 🎉\n\n"
            f"📦 <b>Sản phẩm:</b> {title}\n"
        )
        if sku_name:
            success_text += f"🏷️ <b>Phân loại:</b> <b>{sku_name}</b>\n"
        if price:
            success_text += f"💰 <b>Giá:</b> <code>{price}</code>\n"
        success_text += "\n👉 Gõ <code>/cart</code> để xem toàn bộ giỏ hàng và kiểm tra giá sau Voucher ngay!"
        await query.edit_message_text(success_text, parse_mode="HTML")
    else:
        err_msg = res.get("message", "Lỗi không xác định khi thêm vào giỏ.")
        await query.edit_message_text(f"❌ {err_msg}")

    context.user_data.pop("add_cart_session", None)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lệnh /add <link> để thêm sản phẩm vào giỏ"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    raw_text = " ".join(context.args) if context.args else ""
    url = extract_lazada_url(raw_text)

    if not url:
        help_text = (
            "📌 <b>Hướng dẫn thêm sản phẩm vào giỏ hàng:</b>\n\n"
            "• Gõ lệnh kèm link: <code>/add &lt;link sản phẩm Lazada&gt;</code>\n"
            "• Hoặc đơn giản là <b>dán thẳng link Lazada vào chat</b> này (hỗ trợ cả link app <code>s.lazada.vn</code>)!\n\n"
            "Bot sẽ tự động tải các phân loại (màu sắc, cấu hình, kích cỡ) để bạn bấm chọn trước khi thêm."
        )
        await msg.reply_html(help_text)
        return

    await handle_lazada_product_link(update, context, url)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tự động phát hiện khi người dùng gửi link Lazada hoặc paste chuỗi JSON cookie trực tiếp"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    # 1. Tự động nhận diện nếu tin nhắn chứa link sản phẩm Lazada
    laz_url = extract_lazada_url(text)
    if laz_url:
        await handle_lazada_product_link(update, context, laz_url)
        return

    # 2. Nhận diện nếu tin nhắn chứa JSON cookie hoặc chuỗi cookie Lazada
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
            close_shared_driver()
            dashboard.set_cookie_status(True)
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

    is_online, latency = await asyncio.to_thread(check_internet)
    badge = format_net_badge(is_online, latency)
    if not is_online:
        await status_msg.edit_text("❌ Bot đang bị mất kết nối Internet trên host. Vui lòng thử lại sau.")
        print_cli(f"[dim][{datetime.now().strftime('%H:%M:%S')}][/] {badge} [bold red][Telegram /cart] Mất kết nối Internet![/]")
        return

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: scrape_cart(headless=True))

    if result["status"] == "need_login":
        dashboard.set_cookie_status(False)
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

    dashboard.set_cookie_status(True)
    products = result["products"]
    summary = result.get("summary", {})
    dashboard.update_cart(products, summary)
    print_cli(f"[dim][{datetime.now().strftime('%H:%M:%S')}][/] {badge} [bold cyan][Telegram /cart][/] Đọc thành công {len(products)} SKU | Tổng: [bold green]{summary.get('Total', '0₫')}[/]")
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

    if result["status"] == "need_login":
        dashboard.set_cookie_status(False)
        await status_msg.edit_text(f"❌ {result['message']}")
        return

    if result["status"] != "ok":
        await status_msg.edit_text(f"❌ {result['message']}")
        return

    dashboard.set_cookie_status(True)
    total = result["total_products"]
    changes = result["changes"]
    total_change = result.get("total_change")
    summary = result.get("summary", {})
    if result.get("products"):
        dashboard.update_cart(result["products"], summary)

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


async def setprice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cài đặt mức giá mục tiêu: chỉ gửi thông báo khi giá <= mức này"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    args = context.args or []
    if len(args) < 2:
        history = load_price_history()
        prods = history.get("products", {})

        guide_lines = [
            "🎯 <b>HƯỚNG DẪN ĐẶT MỨC GIÁ MỤC TIÊU:</b>\n",
            "Bot sẽ <b>CHỈ gửi thông báo</b> khi giá sản phẩm giảm xuống <b>thấp hơn hoặc bằng (≤)</b> mức giá bạn đặt.",
            "<i>(Các sản phẩm không cài giá mục tiêu vẫn thông báo biến động như bình thường)</i>\n",
            "👉 <b>Cú pháp:</b> <code>/setprice &lt;STT hoặc Tên&gt; &lt;Mức giá&gt;</code>",
            "Ví dụ:",
            "• <code>/setprice 1 100k</code> (chỉ báo khi SP #1 giảm ≤ 100.000₫)",
            "• <code>/setprice 2 45.000</code>",
            "• <code>/setprice ugreen 50k</code> (tìm theo từ khóa)\n",
        ]

        if prods:
            guide_lines.append("📋 <b>Danh sách sản phẩm trong giỏ hàng:</b>")
            for idx, (pid, p) in enumerate(prods.items(), 1):
                p_name = p.get("name", "Sản phẩm")[:40]
                sku = p.get("sku", "")
                p_sku = f" [{sku[:20]}]" if sku else ""
                cur_p = p.get("current_price")
                cur_str = f"{cur_p:,.0f}₫" if cur_p else "N/A"

                target = get_target_price(pid)
                target_str = f" ➔ 🎯 Mục tiêu: <b>≤ {target:,.0f}₫</b>" if target else ""
                guide_lines.append(f"<b>{idx}.</b> {p_name}{p_sku} - <code>{cur_str}</code>{target_str}")
            guide_lines.append("\n👉 Gõ <code>/setprice &lt;STT&gt; &lt;giá&gt;</code> để cài đặt ngay.")
        else:
            guide_lines.append("ℹ️ <i>Chưa có dữ liệu giỏ hàng. Hãy gửi /cart trước để bot quét sản phẩm.</i>")

        await msg.reply_html("\n".join(guide_lines))
        return

    price_str = args[-1]
    query = " ".join(args[:-1]).strip()
    target_val = parse_user_price(price_str)

    if not target_val or target_val <= 0:
        await msg.reply_html(
            "❌ <b>Mức giá không hợp lệ!</b>\n"
            "Ví dụ các định dạng được hỗ trợ: <code>100k</code>, <code>50.000</code>, <code>150000</code>, <code>1.5tr</code>"
        )
        return

    matched = find_product_by_query(query)
    if not matched:
        await msg.reply_html(
            f"❌ Không tìm thấy sản phẩm nào khớp với: <code>{query}</code>\n"
            f"👉 Hãy gõ <code>/cart</code> hoặc <code>/setprice</code> để xem danh sách STT."
        )
        return

    pid, p_data, idx = matched
    name = p_data.get("name", "Sản phẩm")
    sku = p_data.get("sku", "")
    curr_p = p_data.get("current_price") or 0

    set_target_price(pid, name, sku, target_val, p_data.get("url", ""))

    sku_text = f"🏷️ <i>Phân loại: <b>{sku}</b></i>\n" if sku else ""
    await msg.reply_html(
        f"🎯 <b>ĐÃ ĐẶT MỨC GIÁ MỤC TIÊU THÀNH CÔNG!</b>\n\n"
        f"📦 <b>Sản phẩm #{idx}:</b> {name[:60]}\n"
        f"{sku_text}"
        f"💰 Giá hiện tại: <code>{curr_p:,.0f}₫</code>\n"
        f"🎯 Giá mục tiêu: <b>≤ {target_val:,.0f}₫</b>\n\n"
        f"🔔 <b>Quy tắc thông báo:</b>\n"
        f"• Bot sẽ <b>CHỈ gửi thông báo</b> khi giá sản phẩm này giảm xuống <b>≤ {target_val:,.0f}₫</b>.\n"
        f"• Nếu giá thay đổi nhưng vẫn > {target_val:,.0f}₫, bot sẽ bỏ qua thông báo.\n"
        f"• Các sản phẩm khác trong giỏ vẫn thông báo như bình thường.\n\n"
        f"👉 Gõ <code>/targets</code> để xem danh sách đang theo dõi."
    )


async def delprice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xóa mức giá mục tiêu: quay lại thông báo biến động bình thường"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    args = context.args or []
    if not args:
        await msg.reply_html(
            "👉 <b>Cú pháp xóa giá mục tiêu:</b>\n"
            "• <code>/delprice &lt;STT hoặc tên&gt;</code> (VD: <code>/delprice 1</code>)\n"
            "• <code>/delprice all</code> (Xóa toàn bộ mức giá mục tiêu đã đặt)"
        )
        return

    query = " ".join(args).strip()
    if query.lower() in ("all", "tat ca", "tất cả"):
        count = clear_all_target_prices()
        await msg.reply_html(f"✅ <b>Đã xóa toàn bộ {count} mức giá mục tiêu!</b>\nTừ giờ bot sẽ thông báo mọi biến động giá cho tất cả sản phẩm.")
        return

    matched = find_product_by_query(query)
    if not matched:
        await msg.reply_html(f"❌ Không tìm thấy sản phẩm nào khớp với: <code>{query}</code>")
        return

    pid, p_data, idx = matched
    if remove_target_price(pid):
        name = p_data.get("name", "Sản phẩm")[:60]
        await msg.reply_html(
            f"✅ <b>Đã xóa mức giá mục tiêu cho SP #{idx}:</b> {name}\n\n"
            f"🔔 Sản phẩm này sẽ nhận thông báo mọi biến động giá như bình thường."
        )
    else:
        await msg.reply_text("ℹ️ Sản phẩm này trước đó chưa cài đặt mức giá mục tiêu.")


async def targets_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem danh sách các sản phẩm đang được cài đặt mức giá mục tiêu"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    targets = get_all_target_prices()
    if not targets:
        await msg.reply_html(
            "ℹ️ <b>Hiện chưa có sản phẩm nào được cài đặt mức giá mục tiêu.</b>\n\n"
            "Tất cả sản phẩm trong giỏ hàng đang được theo dõi và gửi thông báo khi có bất kỳ biến động nào.\n\n"
            "👉 Để cài mức giá mong muốn: <code>/setprice &lt;STT&gt; &lt;giá&gt;</code> (VD: <code>/setprice 1 100k</code>)"
        )
        return

    history = load_price_history()
    hist_prods = history.get("products", {})

    lines = ["🎯 <b>DANH SÁCH GIÁ MỤC TIÊU ĐANG THEO DÕI:</b>\n"]
    for idx, (pid, data) in enumerate(targets.items(), 1):
        name = data.get("name", "Sản phẩm")[:55]
        sku = data.get("sku", "")
        sku_str = f"   🏷️ <i>Phân loại: {sku}</i>\n" if sku else ""
        target_p = data.get("target_price", 0)

        hist_p = hist_prods.get(pid, {})
        curr_p = hist_p.get("current_price")
        curr_str = f"{curr_p:,.0f}₫" if curr_p else "N/A"

        if curr_p and curr_p <= target_p:
            status_tag = "🎉 <b>ĐÃ ĐẠT!</b>"
        else:
            diff = curr_p - target_p if curr_p else 0
            status_tag = f"⏳ <i>Cần giảm thêm {diff:,.0f}₫</i>" if diff > 0 else "⏳ <i>Đang chờ...</i>"

        lines.append(
            f"<b>{idx}. {name}</b>\n"
            f"{sku_str}"
            f"   🎯 Mục tiêu: <b>≤ {target_p:,.0f}₫</b>\n"
            f"   💰 Hiện tại: <code>{curr_str}</code> ({status_tag})\n"
        )

    lines.append("👉 Xóa mục tiêu: <code>/delprice &lt;STT&gt;</code> hoặc <code>/delprice all</code>")
    await msg.reply_html("\n".join(lines))


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
        dashboard.set_subscribers_count(len(get_subscribers()))
        if update.effective_message:
            await update.effective_message.reply_text("✅ Bạn đã đăng ký nhận thông báo biến động giá tự động!")


async def unsub_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        remove_subscriber(chat_id)
        dashboard.set_subscribers_count(len(get_subscribers()))
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
    """Khởi động tác vụ background scheduler khi bot chạy"""
    asyncio.create_task(start_scheduler_loop(application.bot))
    dashboard.set_subscribers_count(len(get_subscribers()))
    is_online, latency = await asyncio.to_thread(check_internet)
    badge = format_net_badge(is_online, latency)
    print_cli(f"{badge} [bold green]Father Bot Telegram đã kết nối thành công![/] (Subscribers: {len(get_subscribers())})")


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

    is_online, latency = check_internet()
    badge = format_net_badge(is_online, latency)
    print_cli(f"{badge} [*] Khởi động Father Bot Telegram + Auto Scheduler...")
    app = Application.builder().token(token).post_init(post_init).build()

    # Handlers cơ bản
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping_command))

    # Handlers giỏ hàng & giá
    app.add_handler(CommandHandler("cart", cart_command))
    app.add_handler(CommandHandler("track", track_command))
    app.add_handler(CommandHandler("prices", prices_command))
    app.add_handler(CommandHandler("add", add_command))

    # Handlers cài đặt giá mục tiêu
    app.add_handler(CommandHandler("setprice", setprice_command))
    app.add_handler(CommandHandler("gia", setprice_command))
    app.add_handler(CommandHandler("delprice", delprice_command))
    app.add_handler(CommandHandler("unsetprice", delprice_command))
    app.add_handler(CommandHandler("target", targets_command))
    app.add_handler(CommandHandler("targets", targets_command))

    # Handler chọn phân loại và thêm vào giỏ hàng qua nút bấm
    app.add_handler(CallbackQueryHandler(handle_add_cart_callback, pattern=r"^addcart:"))

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
