#include "host_cli.h"
#include <iostream>
#include <cstdlib>

using namespace std;

static string getPythonExecutable()
{
#ifdef _WIN32
    return "python";
#else
    return "python3";
#endif
}

HostCLI::HostCLI()
    : CmdLineInterface("LazBot> ")
{
}

HostCLI::HostCLI(const string& prompt)
    : CmdLineInterface(prompt)
{
}

void HostCLI::initCmd()
{
    // Đăng ký các chức năng CLI vào bảng lệnh của lớp cơ sở CmdLineInterface
    addCmd("help", CLI_CAST(&HostCLI::cmdHelp));
    addCmd("prices", CLI_CAST(&HostCLI::cmdPrices));
    addCmd("list", CLI_CAST(&HostCLI::cmdPrices));
    addCmd("targets", CLI_CAST(&HostCLI::cmdTargets));
    addCmd("target", CLI_CAST(&HostCLI::cmdTargets));
    addCmd("setprice", CLI_CAST(&HostCLI::cmdSetPrice));
    addCmd("delprice", CLI_CAST(&HostCLI::cmdDelPrice));
    addCmd("cart", CLI_CAST(&HostCLI::cmdCart));
    addCmd("scan", CLI_CAST(&HostCLI::cmdCart));
    addCmd("track", CLI_CAST(&HostCLI::cmdTrack));
    addCmd("cookie", CLI_CAST(&HostCLI::cmdCookie));
    addCmd("bot", CLI_CAST(&HostCLI::cmdBot));
    addCmd("db", CLI_CAST(&HostCLI::cmdDb));
    addCmd("clear", CLI_CAST(&HostCLI::cmdClear));
    addCmd("cls", CLI_CAST(&HostCLI::cmdClear));
}

void HostCLI::initConsole()
{
#ifdef _WIN32
    system("chcp 65001 > nul");
#endif
    printBanner();
}

void HostCLI::printBanner()
{
    cout << "======================================================================" << endl;
    cout << "          LAZADA TRACKER & BOT MANAGER - HOST CLI INTERFACE           " << endl;
    cout << "          (Kế thừa từ CmdLineInterface - C++ Native Engine)           " << endl;
    cout << "======================================================================" << endl;
    cout << " Gõ 'help' để xem danh sách các lệnh hỗ trợ." << endl;
    cout << " Gõ 'quit' hoặc 'exit' để thoát khỏi giao diện dòng lệnh." << endl;
    cout << "======================================================================" << endl;
    cout << endl;
}

void HostCLI::executeBackend(const string& cmdArgs)
{
    string fullCmd = getPythonExecutable() + " cli_backend.py " + cmdArgs;
    int ret = system(fullCmd.c_str());
    (void)ret;
}

void HostCLI::cmdHelp(string argv[], int argc)
{
    (void)argv;
    (void)argc;
    cout << endl;
    cout << "DANH SÁCH CÁC LỆNH HỖ TRỢ TRÊN HOST CLI:" << endl;
    cout << "----------------------------------------------------------------------" << endl;
    cout << " 1. Giỏ hàng & Giá sản phẩm:" << endl;
    cout << "    • prices / list           : Xem bảng giá các mặt hàng đã lưu trong CSDL" << endl;
    cout << "    • cart / scan             : Quét giỏ hàng Lazada & tính Giá Cuối Cùng" << endl;
    cout << "    • track                   : Quét & kiểm tra biến động giá ngay lập tức" << endl;
    cout << endl;
    cout << " 2. Cài đặt Giá đáy Săn sale (Target Price):" << endl;
    cout << "    • setprice <STT/Tên> <Giá>: Cài mức giá đáy (VD: setprice 1 100k)" << endl;
    cout << "    • delprice <STT/all>      : Xóa mức giá đáy (VD: delprice 1, delprice all)" << endl;
    cout << "    • targets                 : Xem danh sách các mặt hàng đang cài giá đáy" << endl;
    cout << endl;
    cout << " 3. Tài khoản & Cookie Lazada:" << endl;
    cout << "    • cookie status           : Kiểm tra trạng thái đăng nhập cookie" << endl;
    cout << "    • cookie set <chuỗi>      : Nạp cookie mới vào hệ thống" << endl;
    cout << endl;
    cout << " 4. Quản lý Bot Telegram trên Host:" << endl;
    cout << "    • bot status              : Kiểm tra bot Telegram có đang chạy không" << endl;
    cout << "    • bot start               : Khởi động bot Telegram chạy nền trên host" << endl;
    cout << "    • bot stop                : Dừng tiến trình bot Telegram" << endl;
    cout << endl;
    cout << " 5. Quản lý CSDL SQLite (lazbot.db):" << endl;
    cout << "    • db info                 : Xem thống kê dung lượng và các bảng dữ liệu" << endl;
    cout << "    • db backup               : Tạo bản sao lưu dự phòng cho CSDL" << endl;
    cout << endl;
    cout << " 6. Tiện ích hệ thống:" << endl;
    cout << "    • clear / cls             : Xóa màn hình console" << endl;
    cout << "    • quit / exit / q         : Thoát chương trình" << endl;
    cout << "----------------------------------------------------------------------" << endl;
    cout << endl;
}

void HostCLI::cmdPrices(string argv[], int argc)
{
    (void)argv;
    (void)argc;
    executeBackend("prices");
}

void HostCLI::cmdTargets(string argv[], int argc)
{
    (void)argv;
    (void)argc;
    executeBackend("targets");
}

void HostCLI::cmdSetPrice(string argv[], int argc)
{
    if (argc < 3)
    {
        cout << "[!] Cú pháp: setprice <STT hoặc Tên SP> <Mức giá đáy>" << endl;
        cout << "    Ví dụ: setprice 1 100k" << endl;
        cout << "           setprice 2 45.000" << endl;
        cout << "           setprice ugreen 50k" << endl;
        return;
    }
    string query = argv[1];
    string price = argv[2];
    executeBackend("setprice \"" + query + "\" \"" + price + "\"");
}

void HostCLI::cmdDelPrice(string argv[], int argc)
{
    if (argc < 2)
    {
        cout << "[!] Cú pháp: delprice <STT hoặc Tên SP hoặc 'all'>" << endl;
        cout << "    Ví dụ: delprice 1" << endl;
        cout << "           delprice all (xóa toàn bộ giá đáy)" << endl;
        return;
    }
    string query = argv[1];
    executeBackend("delprice \"" + query + "\"");
}

void HostCLI::cmdCart(string argv[], int argc)
{
    (void)argv;
    (void)argc;
    executeBackend("cart");
}

void HostCLI::cmdTrack(string argv[], int argc)
{
    (void)argv;
    (void)argc;
    executeBackend("track");
}

void HostCLI::cmdCookie(string argv[], int argc)
{
    if (argc < 2 || argv[1] == "status")
    {
        executeBackend("cookie_status");
    }
    else if (argv[1] == "set")
    {
        if (argc < 3)
        {
            cout << "[!] Cú pháp: cookie set <chuỗi_cookie>" << endl;
            return;
        }
        string fullCookie = "";
        for (int i = 2; i < argc; i++)
        {
            if (i > 2) fullCookie += " ";
            fullCookie += argv[i];
        }
        executeBackend("cookie_set \"" + fullCookie + "\"");
    }
    else
    {
        cout << "[!] Cú pháp: cookie [status | set <chuỗi_cookie>]" << endl;
    }
}

void HostCLI::cmdBot(string argv[], int argc)
{
    if (argc < 2 || argv[1] == "status")
    {
        executeBackend("bot_status");
    }
    else if (argv[1] == "start")
    {
        executeBackend("bot_start");
    }
    else if (argv[1] == "stop")
    {
        executeBackend("bot_stop");
    }
    else
    {
        cout << "[!] Cú pháp: bot [status | start | stop]" << endl;
    }
}

void HostCLI::cmdDb(string argv[], int argc)
{
    if (argc < 2 || argv[1] == "info")
    {
        executeBackend("db_info");
    }
    else if (argv[1] == "backup")
    {
        executeBackend("db_backup");
    }
    else
    {
        cout << "[!] Cú pháp: db [info | backup]" << endl;
    }
}

void HostCLI::cmdClear(string argv[], int argc)
{
    (void)argv;
    (void)argc;
    clearScreen();
    printBanner();
}
