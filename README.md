# 🛒 Lazada Cart Price Tracker & Telegram Bot (Anti-Detect)

Bot Telegram theo dõi biến động giá tự động cho toàn bộ sản phẩm và từng phân loại (SKU) trong giỏ hàng Lazada Việt Nam, tích hợp công nghệ Anti-detect Headless và tự động áp mã Voucher.

---

## ✨ Tính Năng Nổi Bật

- 🛡️ **Anti-Detect Headless Automation**: Sử dụng Selenium kết hợp CDP (Chrome DevTools Protocol) để nạp cookie trực tiếp và vượt qua hệ thống kiểm duyệt bot mà không cần mở cửa sổ trình duyệt.
- 🎯 **Đọc Giá Thực Sau Voucher**: Tự động tick checkbox "Chọn tất cả" ngay tại giao diện giỏ hàng để Lazada kích hoạt Voucher & Khuyến mãi, sau đó trích xuất **Giá Cuối Cùng (Final Price)**.
- 🚫 **An Toàn Tuyệt Đối**: Tuyệt đối **KHÔNG BAO GIỜ** click vào nút thanh toán (Checkout / Confirm Cart). Mọi thao tác chỉ diễn ra trong phạm vi trang giỏ hàng.
- 🔍 **Theo Dõi Độc Lập Từng Phân Loại (SKU)**: Theo dõi riêng từng màu sắc, kích thước, cấu hình của mỗi mặt hàng trong giỏ.
- ⏰ **Tần Suất Quét Siêu Tốc**: Quét tự động **1 phút / lần** liên tục để bắt trọn mọi đợt giảm giá chớp nhoáng (Flash Sale) và voucher mới.
- 📢 **Cảnh Báo Telegram Chi Tiết**: 
  - Tự động thông báo ngay khi có sản phẩm tăng/giảm giá hoặc thay đổi trạng thái tồn kho.
  - Gửi kèm đầy đủ **tên phân loại (SKU)** và **link mua hàng trực tiếp**.
  - Tự động cảnh báo khi Cookie hết hạn phiên đăng nhập để người dùng kịp thời cập nhật.
- 🛍️ **Thêm Vào Giỏ Hàng Trực Tiếp Bằng Link**: Gửi link sản phẩm Lazada (web hoặc app `s.lazada.vn`) hoặc lệnh `/add <link>`, bot sẽ tải thông tin và hiển thị danh sách phân loại (SKU) bằng nút bấm để bạn chọn và tự động thêm vào giỏ hàng.
- 🍪 **Hỗ Trợ Nạp Cookie Linh Hoạt**: Nạp trực tiếp qua console khi khởi động trên Termux, gửi file `cookie.json` hoặc dán JSON vào chat Telegram.

---

## 🚀 Hướng Dẫn Cài Đặt

### 1. Yêu Cầu Hệ Thống
- Python 3.10+
- Google Chrome & ChromeDriver tương thích

### 2. Cài Đặt Thư Viện
```bash
git clone https://github.com/TTr06/Laz_bot.git
cd Laz_bot
pip install -r requirements.txt
```

### 3. Cấu Hình
1. **Telegram Bot Token**:
   - Sao chép `.env.example` thành `.env`:
     ```bash
     cp .env.example .env
     ```
   - Điền Token bot Telegram của bạn vào `.env`:
     ```env
     TELEGRAM_BOT_TOKEN=your_bot_token_here
     ```

2. **Cookie Lazada**:
   - Dùng extension trình duyệt như [Cookie-Editor](https://cookie-editor.com/) xuất toàn bộ cookie từ trang `https://www.lazada.vn` ra dạng JSON.
   - Lưu vào file `cookie.json` trong thư mục gốc dự án (tham khảo mẫu tại `cookie.example.json`).

---

## 🎮 Khởi Chạy

```bash
python bot.py
```

Sau khi bot chạy, mở Telegram và gõ lệnh `/start` vào bot của bạn để bắt đầu sử dụng.

---

## 📖 Danh Sách Lệnh Telegram

| Lệnh | Mô tả |
| :--- | :--- |
| `/start` | Đăng ký nhận thông báo và xem hướng dẫn |
| `/cart` | Quét giỏ hàng, tick chọn tất cả và đọc Giá Cuối Cùng |
| `/track` | Kiểm tra biến động giá các phân loại ngay lập tức |
| `/prices` | Xem bảng tổng hợp giá đã lưu trong lịch sử |
| `/schedule` | Xem trạng thái lịch quét và thời gian lần check tiếp theo |
| `/check_now` | Kích hoạt quét tự động ngay 1 lượt |
| `/auto_on` / `/auto_off` | Bật / Tắt chế độ quét tự động |
| `/cookie <json>` | Nạp cookie mới trực tiếp qua chat Telegram |
| `/cookie_status` | Kiểm tra tình trạng cookie hiện tại |
| `/sub` / `/unsub` | Đăng ký hoặc hủy nhận thông báo tự động |

---

## 🔒 Bản Quyền & Trách Nhiệm

Dự án được xây dựng phục vụ mục đích nghiên cứu và tự động hóa cá nhân. Vui lòng tuân thủ điều khoản dịch vụ của nền tảng khi sử dụng.
