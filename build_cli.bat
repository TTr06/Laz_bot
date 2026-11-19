@echo off
echo [*] Bien dich LazBot Host CLI...
g++ -std=c++17 -O2 cli.cpp host_cli.cpp main.cpp -o lazcli.exe
if %ERRORLEVEL% EQU 0 (
    echo [OK] Bien dich thanh cong: lazcli.exe
    echo [*] Chay './lazcli.exe' de mo giao dien CLI.
) else (
    echo [!] Loi bien dich!
)
