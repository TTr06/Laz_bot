#!/usr/bin/env bash
# ======================================================================
#  LAZADA TRACKER & FATHER BOT - WEB CLI LAUNCHER (LAN / WI-FI)
#  Tuong thich ca Linux, macOS va Android Termux
# ======================================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "======================================================================"
echo "   LAZADA TRACKER & FATHER BOT - WEB CLI LAUNCHER (LAN / WI-FI)"
echo "======================================================================"
echo ""

if command -v ttyd &> /dev/null; then
    echo "[*] Phát hiện ttyd trên hệ thống. Khởi chạy qua cổng 7681..."
    echo "[*] Bạn có thể tắt/khóa màn hình điện thoại, bot vẫn chạy 24/7."
    echo ""
    ttyd -p 7681 python3 main.py
else
    echo "[*] Khởi chạy Web CLI Server tích hợp trên cổng 8080..."
    echo "[*] Mở trình duyệt trên điện thoại/máy tính cùng Wi-Fi để truy cập."
    echo ""
    python3 main.py --web
fi
