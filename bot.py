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
import re
import sys
from datetime import datetime
from typing import Tuple, List, Dict, Optional, Any

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
import database

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
    format_bytes,
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
        f"🤖 <b>LazBot</b> - Công cụ theo dõi giá giỏ hàng Lazada và săn giảm giá tự động.\n\n"
        f"⚡ <b>TÍNH NĂNG CHÍNH:</b>\n"
        f"• Tự động chọn tất cả sản phẩm để tính <b>Giá cuối cùng</b> (sau Voucher sàn, Shop & LazCoins).\n"
        f"• Theo dõi độc lập từng lớp phân loại (Màu sắc, Kích cỡ, Chất liệu...).\n"
        f"• <b>Cài đặt Giá đáy (<code>/setprice</code>)</b>: Chỉ gửi cảnh báo khi giá chạm hoặc thấp hơn mức mong muốn.\n"
        f"• Thêm sản phẩm nhanh vào giỏ: Gửi link sản phẩm trực tiếp vào chat.\n"
        f"• Cơ sở dữ liệu SQLite tốc độ cao, đảm bảo số thứ tự (STT) luôn chuẩn xác 100%.\n\n"
        f"📋 Gõ <code>/help</code> để xem danh sách lệnh hướng dẫn."
    )
    if update.effective_message:
        await update.effective_message.reply_html(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    text = (
        "📖 <b>HƯỚNG DẪN SỬ DỤNG LAZBOT:</b>\n\n"
        "🛒 <b>Giỏ hàng & Theo dõi giá:</b>\n"
        "• <code>/cart</code> : Quét giỏ hàng & tính Giá cuối sau voucher\n"
        "• <code>/track</code> : Kiểm tra biến động giá ngay lập tức\n"
        "• <code>/prices</code> : Xem danh sách giá các mặt hàng đã lưu\n"
        "• <code>/add &lt;link&gt;</code> : Thêm sản phẩm vào giỏ hàng\n\n"
        "🎯 <b>Cài đặt Giá đáy (Săn sale):</b>\n"
        "• <code>/setprice &lt;STT&gt; &lt;giá&gt;</code> : Đặt giá đáy (VD: <code>/setprice 1 100k</code>)\n"
        "• <code>/targets</code> : Xem danh sách các mặt hàng đang cài giá đáy\n"
        "• <code>/delprice &lt;STT&gt;</code> : Xóa giá đáy (quay lại báo mọi biến động)\n\n"
        "⏰ <b>Tự động quét ngầm:</b>\n"
        "• <code>/schedule</code> : Tình trạng lịch quét ngầm\n"
        "• <code>/auto_on</code> / <code>/auto_off</code> : Bật / tắt quét ngầm\n\n"
        "🔑 <b>Cookie & Tài khoản:</b>\n"
        "• <code>/cookie &lt;JSON/text&gt;</code> : Nạp cookie mới\n"
        "• <code>/cookie_status</code> : Kiểm tra trạng thái đăng nhập\n"
        "• <code>/ping</code> : Kiểm tra phản hồi bot\n"
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


def _render_product_selection(session: dict) -> Tuple[str, InlineKeyboardMarkup]:
    """Tạo giao diện hiển thị thông tin sản phẩm và bàn phím chọn từng lớp phân loại"""
    title = session.get("title") or "Sản phẩm Lazada"
    price = session.get("price") or "N/A"
    orig_price = session.get("orig_price")
    layers = session.get("layers") or []
    current_step = session.get("current_step", 0)
    chosen_options = session.get("chosen_options", [])

    price_line = f"💰 <b>Giá:</b> <code>{price}</code>"
    if orig_price and orig_price != price:
        price_line += f" <s>{orig_price}</s>"

    header = (
        f"🛍️ <b>THÔNG TIN SẢN PHẨM</b>\n\n"
        f"📦 <b>{title}</b>\n"
        f"{price_line}\n"
    )

    # Hiển thị tóm tắt tất cả các lớp phân loại hiện có
    if layers:
        layer_summary = ["📋 <b>Các lớp phân loại:</b>"]
        for idx, lyr in enumerate(layers):
            lyr_name = lyr.get("name", f"Lớp {idx+1}")
            opts = [o.get("name", "") for o in lyr.get("options", [])[:6]]
            opts_str = ", ".join(opts)
            if len(lyr.get("options", [])) > 6:
                opts_str += ", ..."
            layer_summary.append(f"• <b>{lyr_name}:</b> {opts_str}")
        header += "\n" + "\n".join(layer_summary) + "\n"

    # Hiển thị các lựa chọn đã chốt ở các bước trước (nếu có)
    if chosen_options:
        chosen_lines = []
        for c_idx, c_val in enumerate(chosen_options):
            l_name = layers[c_idx].get("name", f"Lớp {c_idx+1}")
            chosen_lines.append(f"✅ <i>{l_name}:</i> <b>{c_val}</b>")
        header += "\n" + "\n".join(chosen_lines) + "\n"

    # Nếu sản phẩm không có phân loại nào
    if not layers:
        text = header + "\n<i>(Sản phẩm có 1 phân loại mặc định)</i>"
        keyboard = [
            [InlineKeyboardButton("🛒 Thêm vào giỏ hàng ngay", callback_data="addcart:default")],
            [InlineKeyboardButton("❌ Hủy", callback_data="addcart:cancel")]
        ]
        return text, InlineKeyboardMarkup(keyboard)

    # Hiển thị các nút bấm chọn cho lớp hiện tại
    cur_layer = layers[current_step]
    cur_name = cur_layer.get("name", f"Lớp {current_step+1}")
    total_steps = len(layers)

    step_prompt = f"\n👉 <b>Bước {current_step + 1}/{total_steps}: Chọn {cur_name}</b>"
    text = header + step_prompt

    keyboard = []
    row = []
    for o_idx, opt in enumerate(cur_layer.get("options", [])):
        opt_name = opt.get("name", "")
        row.append(InlineKeyboardButton(opt_name, callback_data=f"addcart:step:{current_step}:{o_idx}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Hàng nút điều hướng
    nav_row = []
    if current_step > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Quay lại", callback_data="addcart:back"))
    nav_row.append(InlineKeyboardButton("❌ Hủy", callback_data="addcart:cancel"))
    keyboard.append(nav_row)

    return text, InlineKeyboardMarkup(keyboard)


async def handle_lazada_product_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    """Xử lý link sản phẩm Lazada: lấy thông tin chi tiết và hiển thị chọn từng lớp phân loại"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    status_msg = await msg.reply_text("🔍 Đang tải thông tin sản phẩm và phân loại từ Lazada...")

    loop = asyncio.get_running_loop()
    details = await loop.run_in_executor(None, lambda: fetch_product_details(url, headless=True))

    if details.get("status") != "ok":
        err_msg = details.get("message", "Không thể lấy thông tin sản phẩm từ link này.")
        await status_msg.edit_text(f"❌ {err_msg}")
        return

    title = details.get("title") or "Sản phẩm Lazada"
    price = details.get("price") or "N/A"
    orig_price = details.get("original_price")
    layers = details.get("layers") or []
    prod_url = details.get("url") or url

    # Khởi tạo phiên chọn sản phẩm trong context
    session = {
        "url": prod_url,
        "title": title,
        "price": price,
        "orig_price": orig_price,
        "layers": layers,
        "current_step": 0,
        "chosen_options": []
    }
    context.user_data["add_cart_session"] = session

    text, markup = _render_product_selection(session)
    await status_msg.edit_text(text, parse_mode="HTML", reply_markup=markup)


async def handle_add_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý điều hướng khi người dùng chọn từng lớp phân loại để thêm vào giỏ"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    if not data.startswith("addcart:"):
        return

    action = data.split(":", 1)[1]
    if action == "cancel":
        await query.edit_message_text("❌ Đã hủy thao tác thêm sản phẩm.")
        context.user_data.pop("add_cart_session", None)
        return

    session = context.user_data.get("add_cart_session")
    if not session:
        await query.edit_message_text("⚠️ Phiên chọn đã hết hạn. Vui lòng gửi lại link sản phẩm.")
        return

    layers = session.get("layers", [])
    current_step = session.get("current_step", 0)
    chosen_options = session.get("chosen_options", [])

    if action == "back":
        if current_step > 0:
            session["current_step"] -= 1
            if session["chosen_options"]:
                session["chosen_options"].pop()
        text, markup = _render_product_selection(session)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        return

    if action.startswith("step:"):
        # addcart:step:<layer_idx>:<opt_idx>
        parts = action.split(":")
        layer_idx = int(parts[1])
        opt_idx = int(parts[2])

        if layer_idx < len(layers):
            chosen_opt = layers[layer_idx]["options"][opt_idx]["name"]
            chosen_options.append(chosen_opt)
            session["chosen_options"] = chosen_options
            session["current_step"] = layer_idx + 1

        # Nếu còn lớp phân loại tiếp theo -> render bước kế tiếp
        if session["current_step"] < len(layers):
            text, markup = _render_product_selection(session)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
            return

    # Khi đã chọn đủ tất cả các lớp phân loại (hoặc action == 'default')
    url = session.get("url")
    title = session.get("title")
    price = session.get("price")
    chosen = session.get("chosen_options", [])
    sku_display = " / ".join(chosen) if chosen else ""
    sku_text = f" [<b>{sku_display}</b>]" if sku_display else ""

    await query.edit_message_text(f"⏳ Đang thêm{sku_text} vào giỏ hàng Lazada...", parse_mode="HTML")

    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, lambda: add_sku_to_cart(url, chosen, headless=True))

    if res.get("status") == "ok":
        msg_text = (
            f"✅ <b>ĐÃ THÊM VÀO GIỎ HÀNG THÀNH CÔNG!</b>\n\n"
            f"📦 <b>Sản phẩm:</b> {title}\n"
        )
        if sku_display:
            msg_text += f"🏷️ <b>Phân loại:</b> <code>{sku_display}</code>\n"
        if price:
            msg_text += f"💰 <b>Giá:</b> <code>{price}</code>\n"
        msg_text += "\n👉 Gõ <code>/cart</code> để xem giỏ hàng và giá sau voucher."
        await query.edit_message_text(msg_text, parse_mode="HTML")
    else:
        err_msg = res.get("message", "Lỗi thao tác.")
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
    try:
        products = database.save_cart_to_db(products, summary)
    except Exception as e:
        logger.error(f"Lỗi lưu SQLite: {e}")
    dashboard.update_cart(products, summary)

    dur = result.get("duration", 0.0)
    bytes_cnt = result.get("data_bytes", 0)
    perf_parts = []
    if dur > 0:
        perf_parts.append(f"⏱️ {dur:.1f}s")
    if bytes_cnt > 0:
        perf_parts.append(f"📶 {format_bytes(bytes_cnt)}")
    perf_str = f" | {' | '.join(perf_parts)}" if perf_parts else ""

    print_cli(f"[dim][{datetime.now().strftime('%H:%M:%S')}][/] [bold cyan][Telegram /cart][/] Đọc thành công {len(products)} SKU | Tổng: [bold green]{summary.get('Total', '0₫')}[/]{perf_str}")
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
    """Cài đặt mức Giá đáy: chỉ gửi thông báo khi giá <= mức này"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    args = context.args or []
    if len(args) < 2:
        cart_items = database.get_cart_items_db(valid_only=True)

        guide_lines = [
            "🎯 <b>CÀI ĐẶT GIÁ ĐÁY</b>\n",
            "Bot chỉ gửi thông báo khi giá sản phẩm giảm xuống <b>≤ mức giá đáy</b> bạn đặt.\n",
            "👉 <b>Cú pháp:</b> <code>/setprice &lt;STT hoặc Tên&gt; &lt;Giá đáy&gt;</code>",
            "Ví dụ:",
            "• <code>/setprice 1 100k</code> (chỉ báo khi SP #1 giảm ≤ 100.000₫)",
            "• <code>/setprice 2 45.000</code>",
            "• <code>/setprice ugreen 50k</code>\n",
        ]

        if cart_items:
            guide_lines.append("📋 <b>Danh sách sản phẩm trong giỏ:</b>")
            for p in cart_items:
                idx = p["stt"]
                p_name = p.get("name", "Sản phẩm")[:40]
                sku = p.get("sku", "")
                p_sku = f" [{sku[:20]}]" if sku else ""
                cur_p = p.get("price")
                cur_str = f"{cur_p:,.0f}₫" if cur_p else "N/A"

                target = get_target_price(p["pid"])
                target_str = f" ➔ 🎯 Giá đáy: <b>≤ {target:,.0f}₫</b>" if target else ""
                guide_lines.append(f"<b>{idx}.</b> {p_name}{p_sku} - <code>{cur_str}</code>{target_str}")
            guide_lines.append("\n👉 Gõ <code>/setprice &lt;STT&gt; &lt;giá&gt;</code> để cài đặt.")
        else:
            guide_lines.append("ℹ️ <i>Chưa có dữ liệu giỏ hàng. Gõ /cart để quét giỏ hàng trước.</i>")

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
            f"👉 Gõ <code>/cart</code> để xem danh sách STT chuẩn xác."
        )
        return

    pid, p_data, idx = matched
    name = p_data.get("name", "Sản phẩm")
    sku = p_data.get("sku", "")
    curr_p = p_data.get("current_price") or 0

    set_target_price(pid, name, sku, target_val, p_data.get("url", ""))

    sku_text = f"🏷️ <i>Phân loại: <b>{sku}</b></i>\n" if sku else ""
    await msg.reply_html(
        f"🎯 <b>ĐÃ CÀI ĐẶT GIÁ ĐÁY THÀNH CÔNG!</b>\n\n"
        f"📦 <b>Sản phẩm #{idx}:</b> {name[:60]}\n"
        f"{sku_text}"
        f"💰 Giá hiện tại: <code>{curr_p:,.0f}₫</code>\n"
        f"🎯 Giá đáy nhận cảnh báo: <b>≤ {target_val:,.0f}₫</b>\n\n"
        f"👉 Gõ <code>/targets</code> để xem danh sách đang theo dõi."
    )


async def delprice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xóa mức Giá đáy của sản phẩm"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    args = context.args or []
    if not args:
        await msg.reply_html(
            "👉 <b>Cú pháp xóa giá đáy:</b>\n"
            "• <code>/delprice &lt;STT hoặc Tên&gt;</code> (VD: <code>/delprice 1</code>)\n"
            "• <code>/delprice all</code> (Xóa toàn bộ giá đáy)"
        )
        return

    query = " ".join(args).strip()
    if query.lower() in ("all", "tat ca", "tất cả"):
        count = clear_all_target_prices()
        await msg.reply_html(f"✅ Đã xóa toàn bộ <b>{count}</b> mức giá đáy.")
        return

    matched = find_product_by_query(query)
    if not matched:
        await msg.reply_html(f"❌ Không tìm thấy sản phẩm khớp với: <code>{query}</code>")
        return

    pid, p_data, idx = matched
    if remove_target_price(pid):
        name = p_data.get("name", "Sản phẩm")[:60]
        await msg.reply_html(f"✅ Đã xóa giá đáy cho <b>SP #{idx}:</b> {name}")
    else:
        await msg.reply_text("ℹ️ Sản phẩm này chưa cài đặt giá đáy.")


async def targets_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem danh sách các sản phẩm đang cài đặt Giá đáy"""
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return

    targets = database.get_all_target_prices_db()
    if not targets:
        await msg.reply_html(
            "ℹ️ <b>Chưa có sản phẩm nào được cài đặt giá đáy.</b>\n\n"
            "👉 Đặt giá đáy: <code>/setprice &lt;STT&gt; &lt;giá&gt;</code> (VD: <code>/setprice 1 100k</code>)"
        )
        return

    lines = ["🎯 <b>DANH SÁCH GIÁ ĐÁY ĐANG THEO DÕI:</b>\n"]
    for row in targets:
        idx = row.get("stt") or "?"
        name = row.get("name", "Sản phẩm")[:55]
        sku = row.get("sku", "")
        sku_str = f"   🏷️ <i>Phân loại: {sku}</i>\n" if sku else ""
        target_p = row.get("target_price", 0)
        curr_p = row.get("current_price")
        curr_str = f"{curr_p:,.0f}₫" if curr_p else "N/A"

        if curr_p and curr_p <= target_p:
            status_tag = "🎉 <b>ĐÃ ĐẠT!</b>"
        else:
            diff = curr_p - target_p if curr_p else 0
            status_tag = f"<i>Cần giảm thêm {diff:,.0f}₫</i>" if diff > 0 else "<i>Đang chờ</i>"

        lines.append(
            f"<b>#{idx}. {name}</b>\n"
            f"{sku_str}"
            f"   🎯 Giá đáy: <b>≤ {target_p:,.0f}₫</b>\n"
            f"   💰 Hiện tại: <code>{curr_str}</code> ({status_tag})\n"
        )

    lines.append("👉 Xóa giá đáy: <code>/delprice &lt;STT&gt;</code> hoặc <code>/delprice all</code>")
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
    print_cli(f"[bold green]Father Bot Telegram đã kết nối thành công![/] (Subscribers: {len(get_subscribers())})")


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

    print_cli("[*] Khởi động Father Bot Telegram + Auto Scheduler...")
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
