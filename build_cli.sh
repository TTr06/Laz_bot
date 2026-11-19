#!/bin/bash
echo "[*] Biên dịch LazBot Host CLI trên Linux/Termux..."
g++ -std=c++17 -O2 cli.cpp host_cli.cpp main.cpp -o lazcli
if [ $? -eq 0 ]; then
    chmod +x lazcli
    echo "[OK] Biên dịch thành công tệp thực thi: ./lazcli"
    echo "[*] Gõ './lazcli' để mở giao diện CLI hoặc './lazcli help' để xem trợ giúp."
else
    echo "[!] Lỗi biên dịch. Hãy đảm bảo bạn đã cài g++ (apt install -y g++ hoặc pkg install -y clang)."
fi
