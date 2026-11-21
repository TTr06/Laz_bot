@echo off
chcp 65001 > nul
title LazBot Web CLI Console
echo ======================================================================
echo    LAZADA TRACKER & FATHER BOT - WEB CLI LAUNCHER (LAN / WI-FI)
echo ======================================================================
echo.

where ttyd >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [*] Phat hien ttyd da duoc cai dat tren he thong.
    echo [*] Dang khoi chay ttyd tren cong 7681...
    echo [*] Mo trinh duyet tren dien thoai/may tinh cung Wi-Fi de truy cap.
    echo.
    ttyd -p 7681 python main.py
) else (
    echo [*] Khoi chay Web CLI Server tich hop tren cong 8080...
    echo [*] Mo trinh duyet tren dien thoai/may tinh cung Wi-Fi de truy cap.
    echo.
    python main.py --web
)
pause
