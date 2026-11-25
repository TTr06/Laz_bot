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
from telegram.request import HTTPXRequest
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
from database import (
    parse_user_price,
    set_target_price,
    remove_target_price,
    clear_all_target_prices,
    get_all_target_prices,
    get_target_price,
    find_product_by_query,
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
        f"Xin chào <b>{user.first_name}</b>!\n\n"
        f"🤖 <b>LazBot</b> - Theo dõi giá giỏ hàng Lazada & săn giá đáy.\n\n"
        f"<b>Lệnh chính:</b>\n"
        f"• <code>/cart</code> : Quét giỏ & tính giá sau voucher\n"
        f"• <code>/prices</code> : Danh sách giá các mặt hàng\n"
        f"• <code>/targets</code> : Mục tiêu giá đáy\n"
        f"• <code>1 100k</code> : Cài giá đáy (STT 1 giá 100k)\n"
        f"• Gửi link sản phẩm để thêm vào giỏ\n\n"
        f"Gõ <code>/help</code> để xem chi tiết."
    )
    if update.effective_message:
        await update.effective_message.reply_html(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    text = (
        "📖 <b>LỆNH SỬ DỤNG:</b>\n\n"
        "🛒 <b>Giỏ hàng & Giá:</b>\n"
        "• <code>/cart</code> : Quét giỏ & tính giá sau voucher\n"
        "• <code>/track</code> : Kiểm tra biến động giá\n"
        "• <code>/prices</code> : Xem giá các mặt hàng\n"
        "• <code>/add &lt;link&gt;</code> : Thêm sản phẩm vào giỏ\n\n"
        "🎯 <b>Giá đáy (Săn sale):</b>\n"
        "• Cài đặt: <code>&lt;STT&gt; &lt;giá&gt;</code> (VD: <code>1 100k</code>, <code>2 1tr5</code>)\n"
        "• Xóa: <code>xoa &lt;STT&gt;</code> (xóa hết: <code>xoa all</code>)\n"
        "• <code>/targets</code> : Danh sách giá đáy\n\n"
        "⏰ <b>Quét ngầm:</b>\n"
        "• <code>/schedule</code> : Lịch quét\n"
        "• <code>/auto_on</code> / <code>/auto_off</code> : Bật / tắt quét ngầm\n\n"
        "🔑 <b>Cookie:</b>\n"
        "• Dán mảng JSON cookie vào chat\n"
        "• <code>/cookie_status</code> : Kiểm tra phiên đăng nhập"
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
    """Tạo giao diện hiển thị thông tin sản phẩm, danh sách phân loại & tổ hợp phân loại"""
    title = session.get("title") or "Sản phẩm Lazada"
    price = session.get("price") or "N/A"
    orig_price = session.get("orig_price")
    layers = session.get("layers") or []
    combinations = session.get("combinations") or []
    current_step = session.get("current_step", 0)
    chosen_options = session.get("chosen_options", [])
    view_mode = session.get("view_mode") or ("combo" if (len(layers) <= 1 or len(combinations) <= 8) else "layers")
    combo_page = session.get("combo_page", 0)

    price_line = f"💰 <b>Giá:</b> <code>{price}</code>"
    if orig_price and orig_price != price:
        price_line += f" <s>{orig_price}</s>"

    header = (
        f"🛍️ <b>THÔNG TIN SẢN PHẨM</b>\n\n"
        f"📦 <b>{title}</b>\n"
        f"{price_line}\n"
    )

    # 1. Hiển thị tóm tắt tất cả các lớp phân loại
    if layers:
        layer_summary = ["📋 <b>Các lớp phân loại:</b>"]
        for idx, lyr in enumerate(layers):
            lyr_name = lyr.get("name", f"Lớp {idx+1}")
            opts = [o.get("name", "") for o in lyr.get("options", [])]
            opts_str = ", ".join(opts[:8])
            if len(opts) > 8:
                opts_str += f", ... (+{len(opts)-8})"
            layer_summary.append(f"• <b>{lyr_name}:</b> {opts_str}")
        header += "\n" + "\n".join(layer_summary) + "\n"

    # 2. Hiển thị danh sách các tổ hợp phân loại (SKU)
    if combinations and len(layers) > 1:
        combo_summary = [f"🧩 <b>Tổ hợp phân loại ({len(combinations)} tổ hợp):</b>"]
        for c_idx, c in enumerate(combinations[:8]):
            c_name = c.get("name", "")
            c_price = f" - <code>{c['price']}</code>" if c.get("price") else ""
            c_stock = " <i>(Hết hàng)</i>" if not c.get("inStock", True) else ""
            combo_summary.append(f" {c_idx+1}. {c_name}{c_price}{c_stock}")
        if len(combinations) > 8:
            combo_summary.append(f" ... và <b>{len(combinations)-8}</b> tổ hợp khác.")
        header += "\n" + "\n".join(combo_summary) + "\n"

    # 3. Hiển thị các lựa chọn đã chốt (trong chế độ chọn từng lớp)
    if chosen_options:
        chosen_lines = []
        for c_idx, c_val in enumerate(chosen_options):
            l_name = layers[c_idx].get("name", f"Lớp {c_idx+1}") if c_idx < len(layers) else f"Lớp {c_idx+1}"
            chosen_lines.append(f"✅ <i>{l_name}:</i> <b>{c_val}</b>")
        header += "\n" + "\n".join(chosen_lines) + "\n"

    # Nếu sản phẩm không có phân loại nào
    if not layers and not combinations:
        text = header + "\n<i>(Sản phẩm có 1 phân loại mặc định)</i>"
        keyboard = [
            [InlineKeyboardButton("🛒 Thêm vào giỏ hàng ngay", callback_data="addcart:default")],
            [InlineKeyboardButton("❌ Hủy", callback_data="addcart:cancel")]
        ]
        return text, InlineKeyboardMarkup(keyboard)

    # Chế độ 1: Chọn trực tiếp theo tổ hợp phân loại
    if view_mode == "combo" and combinations:
        text = header + "\n👉 <b>Chọn tổ hợp để thêm vào giỏ:</b>"
        keyboard = []
        PAGE_SIZE = 8
        total_pages = max(1, (len(combinations) + PAGE_SIZE - 1) // PAGE_SIZE)
        combo_page = max(0, min(combo_page, total_pages - 1))
        start_idx = combo_page * PAGE_SIZE
        page_combos = combinations[start_idx:start_idx + PAGE_SIZE]

        row = []
        for idx_offset, c in enumerate(page_combos):
            actual_idx = start_idx + idx_offset
            c_name = c.get("name", "")
            btn_text = c_name
            if len(btn_text) > 28:
                btn_text = btn_text[:26] + ".."
            row.append(InlineKeyboardButton(btn_text, callback_data=f"addcart:combo:{actual_idx}"))
            if len(row) == 2 or any(len(x.get("name", "")) > 18 for x in page_combos):
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        if total_pages > 1:
            page_nav = []
            if combo_page > 0:
                page_nav.append(InlineKeyboardButton("⬅️ Trước", callback_data=f"addcart:combopage:{combo_page - 1}"))
            page_nav.append(InlineKeyboardButton(f"📄 {combo_page + 1}/{total_pages}", callback_data="addcart:noop"))
            if combo_page < total_pages - 1:
                page_nav.append(InlineKeyboardButton("Sau ➡️", callback_data=f"addcart:combopage:{combo_page + 1}"))
            keyboard.append(page_nav)

        nav_row = []
        if len(layers) > 1:
            nav_row.append(InlineKeyboardButton("🔀 Chọn theo từng lớp", callback_data="addcart:toggle_mode"))
        nav_row.append(InlineKeyboardButton("❌ Hủy", callback_data="addcart:cancel"))
        keyboard.append(nav_row)
        return text, InlineKeyboardMarkup(keyboard)

    # Chế độ 2: Chọn từng bước qua từng lớp
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
        if len(row) == 2 or len(opt_name) > 18:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    nav_row = []
    if current_step > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Quay lại", callback_data="addcart:back"))
    if combinations and len(layers) > 1:
        nav_row.append(InlineKeyboardButton("🧩 Xem danh sách tổ hợp", callback_data="addcart:toggle_mode"))
    nav_row.append(InlineKeyboardButton("❌ Hủy", callback_data="addcart:cancel"))
    keyboard.append(nav_row)

    return text, InlineKeyboardMarkup(keyboard)


async def handle_lazada_product_link(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    """Xử lý link sản phẩm Lazada: lấy thông tin chi tiết và hiển thị phân loại cùng tổ hợp"""
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
    combinations = details.get("combinations") or []
    prod_url = details.get("url") or url

    # Khởi tạo phiên chọn sản phẩm trong context
    session = {
        "url": prod_url,
        "title": title,
        "price": price,
        "orig_price": orig_price,
        "layers": layers,
        "combinations": combinations,
        "current_step": 0,
        "chosen_options": [],
        "view_mode": "combo" if (len(layers) <= 1 or len(combinations) <= 8) else "layers",
        "combo_page": 0
    }
    context.user_data["add_cart_session"] = session

    text, markup = _render_product_selection(session)
    await status_msg.edit_text(text, parse_mode="HTML", reply_markup=markup)


async def handle_add_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý điều hướng khi người dùng chọn phân loại hoặc tổ hợp để thêm vào giỏ"""
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
    combinations = session.get("combinations", [])
    current_step = session.get("current_step", 0)
    chosen_options = session.get("chosen_options", [])

    if action == "noop":
        return

    if action == "toggle_mode":
        cur_mode = session.get("view_mode", "combo")
        session["view_mode"] = "layers" if cur_mode == "combo" else "combo"
        text, markup = _render_product_selection(session)
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
        return

    if action.startswith("combopage:"):
        page = int(action.split(":")[1])
        session["combo_page"] = page
        text, markup = _render_product_selection(session)
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
        return

    if action == "back":
        if current_step > 0:
            session["current_step"] -= 1
            if session["chosen_options"]:
                session["chosen_options"].pop()
        text, markup = _render_product_selection(session)
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
        return

    # Chọn trực tiếp 1 tổ hợp phân loại
    if action.startswith("combo:"):
        combo_idx = int(action.split(":")[1])
        if combo_idx < len(combinations):
            chosen_combo = combinations[combo_idx]
            chosen_parts = chosen_combo.get("parts") or [chosen_combo["name"]]
            session["chosen_options"] = chosen_parts

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
        return

    # Chọn theo từng lớp phân loại
    if action.startswith("step:"):
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
            try:
                await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass
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

    # 3. Lệnh xóa giá đáy nhanh: xoa 1, del 1, 1 0, 1 off, xoa all
    quick_del = database.parse_quick_del_input(text)
    if quick_del:
        action_type, query = quick_del
        if action_type == "ALL":
            count = database.clear_all_target_prices_db()
            await msg.reply_html(
                f"🗑️ <b>Đã xóa toàn bộ giá đáy ({count} sản phẩm).</b>\n"
                f"<i>Tất cả sản phẩm trong giỏ sẽ nhận thông báo khi có bất kỳ thay đổi giá nào.</i>"
            )
            return
        elif action_type == "SINGLE" and query:
            matched = database.find_product_by_stt_or_query(query)
            if matched:
                database.remove_target_price_db(matched["pid"])
                stt = matched["stt"]
                name = matched["name"][:55]
                await msg.reply_html(
                    f"🗑️ <b>Đã hủy giá đáy cho SP #{stt}:</b> {name}\n"
                    f"<i>Sản phẩm này sẽ quay lại nhận thông báo cho mọi biến động giá.</i>"
                )
                return
            else:
                if query.isdigit():
                    await msg.reply_html(
                        f"❌ <b>Không tìm thấy sản phẩm #{query} trong giỏ hàng.</b>\n"
                        f"👉 Gõ <code>/cart</code> để xem danh sách STT chuẩn xác."
                    )
                else:
                    await msg.reply_html(f"❌ Không tìm thấy sản phẩm khớp với: <code>{query}</code>")
                return

    # 4. Hướng dẫn nhanh nếu nhắn từ khóa cài giá
    if text.lower() in ("setprice", "/setprice", "gia day", "giá đáy", "cai gia", "cài giá"):
        await msg.reply_html(
            "💡 <b>CÁCH ĐẶT GIÁ ĐÁY NHANH:</b>\n\n"
            "Nhắn trực tiếp vào chat: <b>&lt;STT&gt; &lt;giá&gt;</b>\n"
            "• <code>1 100k</code> (đặt SP #1 giá đáy 100.000₫)\n"
            "• <code>2 45k</code>, <code>3 1.5tr</code>, <code>4 1tr5</code>\n"
            "• Đặt nhiều SP cùng lúc: <code>1 100k, 2 50k, 3 200k</code>\n"
            "• Xóa giá đáy: <code>xoa 1</code> hoặc <code>1 0</code>\n\n"
            "👉 Gõ <code>/cart</code> để xem danh sách số thứ tự (STT)."
        )
        return

    # 5. Cài đặt giá đáy nhanh qua tin nhắn (đơn lẻ hoặc hàng loạt)
    matched_items, unmatched_queries = database.parse_quick_setprice_input(text)
    if matched_items:
        for p_data, target_val in matched_items:
            database.set_target_price_db(
                p_data["pid"],
                p_data["name"],
                p_data.get("sku", ""),
                target_val,
                p_data.get("url", "")
            )

        if len(matched_items) == 1:
            p, target_val = matched_items[0]
            stt = p["stt"]
            name = p["name"]
            sku = p.get("sku", "")
            cur_price = p.get("price") or 0
            sku_line = f"🏷️ <i>Phân loại: <b>{sku}</b></i>\n" if sku else ""
            unmatched_hint = f"\n⚠️ <i>Không tìm thấy: {', '.join(unmatched_queries)}</i>" if unmatched_queries else ""

            await msg.reply_html(
                f"🎯 <b>Đã cài giá đáy cho SP #{stt}</b>\n\n"
                f"📦 <b>{name[:60]}</b>\n"
                f"{sku_line}"
                f"💰 Giá hiện tại: <code>{cur_price:,.0f}₫</code>\n"
                f"🎯 Giá đáy nhận cảnh báo: <b>≤ {target_val:,.0f}₫</b>\n\n"
                f"<i>Bot chỉ gửi thông báo khi giá giảm xuống ≤ {target_val:,.0f}₫.</i>"
                f"{unmatched_hint}"
            )
            return
        else:
            lines = [f"🎯 <b>Đã cài giá đáy cho {len(matched_items)} sản phẩm:</b>\n"]
            for p, target_val in matched_items:
                stt = p["stt"]
                name = p["name"][:38]
                cur_p = p.get("price") or 0
                lines.append(f"• <b>#{stt}</b> {name} ➔ <b>≤ {target_val:,.0f}₫</b> (Hiện tại: <code>{cur_p:,.0f}₫</code>)")
            lines.append("\n👉 Gõ <code>/targets</code> để xem toàn bộ danh sách đang theo dõi.")
            if unmatched_queries:
                lines.append(f"⚠️ <i>Không tìm thấy sản phẩm: {', '.join(unmatched_queries)}</i>")
            await msg.reply_html("\n".join(lines))
            return

    elif unmatched_queries:
        unm_str = ', '.join([f'#{q}' if q.isdigit() else q for q in unmatched_queries])
        await msg.reply_html(
            f"❌ <b>Không tìm thấy sản phẩm: {unm_str}</b>\n"
            f"👉 Gõ <code>/cart</code> để xem danh sách và số thứ tự (STT) chuẩn xác."
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


def _split_html_chunks(text: str, limit: int = 3800) -> list[str]:
    """Chia văn bản HTML theo dòng để không bao giờ cắt ngang thẻ HTML và vượt quá 4096 ký tự Telegram."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if cur and cur_len + line_len > limit:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_len = line_len
        else:
            cur.append(line)
            cur_len += line_len
    if cur:
        chunks.append("\n".join(cur))
    return chunks


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
    chunks = _split_html_chunks(full_text)
    await status_msg.edit_text(chunks[0], parse_mode="HTML")
    for extra in chunks[1:]:
        await msg.reply_html(extra)


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
            "ℹ️ <b>Chưa có sản phẩm cài giá đáy.</b>\n"
            "👉 Dùng: <code>1 100k</code> (STT 1 giá 100k)"
        )
        return

    lines = ["🎯 <b>DANH SÁCH GIÁ ĐÁY:</b>\n"]
    for row in targets:
        idx = row.get("stt") or "-"
        name = row.get("name", "Sản phẩm")[:55]
        sku = row.get("sku", "").strip()
        sku_str = f"   🏷️ <i>Phân loại: {sku}</i>\n" if sku else ""
        target_p = row.get("target_price", 0)
        curr_p = row.get("current_price")
        is_active = row.get("is_active", 1)

        if not is_active or row.get("stt") is None:
            status_tag = "<i>Vô hiệu (Ngoài giỏ)</i>"
            curr_str = "N/A"
        elif curr_p is None:
            status_tag = "<i>Chờ quét</i>"
            curr_str = "N/A"
        elif curr_p <= target_p:
            status_tag = "🎉 <b>ĐÃ ĐẠT!</b>"
            curr_str = f"{curr_p:,.0f}₫"
        else:
            diff = curr_p - target_p
            status_tag = f"<i>Thiếu {diff:,.0f}₫</i>"
            curr_str = f"{curr_p:,.0f}₫"

        lines.append(
            f"<b>#{idx}. {name}</b>\n"
            f"{sku_str}"
            f"   🎯 Giá đáy: <b>≤ {target_p:,.0f}₫</b>\n"
            f"   💰 Hiện tại: <code>{curr_str}</code> ({status_tag})\n"
        )

    lines.append("👉 Xóa: <code>/delprice &lt;STT&gt;</code> hoặc <code>/delprice all</code>")
    await msg.reply_html("\n".join(lines))


async def prices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_register_user(update)
    msg = update.effective_message
    if not msg:
        return
    text = get_price_summary()
    for chunk in _split_html_chunks(text):
        await msg.reply_html(chunk)


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


def create_bot_app(token: str | None = None) -> Application:
    """Tạo và cấu hình Application với đầy đủ handlers và timeout tối ưu"""
    if not token:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        raise ValueError("Chưa có TELEGRAM_BOT_TOKEN trong file .env")

    request_config = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    app = Application.builder().token(token).request(request_config).post_init(post_init).build()

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

    return app


def main() -> None:
    # 1. Tùy chọn nạp JSON Cookie khi khởi động (Hữu ích khi chạy trên Termux / Console)
    prompt_interactive_cookie()

    # Khởi tạo event loop cho MainThread (sửa lỗi RuntimeError trên Python 3.12, 3.13 và 3.14)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        app = create_bot_app()
    except ValueError as e:
        print(f"[!] Lỗi: {e}")
        return

    print_cli("[*] Khởi động Father Bot Telegram + Auto Scheduler...")
    print("[OK] Bot đã sẵn sàng nhận lệnh từ Telegram.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
