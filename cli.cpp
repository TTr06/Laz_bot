#include "cli.h"
#include <iostream>
#include <cstdlib>
#include <cctype>
#include <algorithm>

using namespace std;

CmdLineInterface::CmdLineInterface()
    : cmdPrompt("LazBot> "), bRunning(true), numCommands(0), cmdDefaulID(CMD_UNKNOWN_ID)
{
    for (int i = 0; i < CMD_MAX_NUM; i++)
    {
        cmdDoFunc[i] = nullptr;
        cmdNameList[i] = "";
    }
}

CmdLineInterface::CmdLineInterface(const string& prompt)
    : cmdPrompt(prompt), bRunning(true), numCommands(0), cmdDefaulID(CMD_UNKNOWN_ID)
{
    for (int i = 0; i < CMD_MAX_NUM; i++)
    {
        cmdDoFunc[i] = nullptr;
        cmdNameList[i] = "";
    }
}

void CmdLineInterface::setCmdPrompt(const string& prompt)
{
    cmdPrompt = prompt;
}

void CmdLineInterface::clearScreen()
{
#ifdef _WIN32
    system("cls");
#else
    system("clear");
#endif
}

void CmdLineInterface::showCmdPrompt()
{
    cout << cmdPrompt;
    cout.flush();
}

void CmdLineInterface::addCmd(const string& name, CLI_CMD_FUNC f)
{
    if (numCommands < CMD_MAX_NUM)
    {
        cmdNameList[numCommands] = name;
        cmdDoFunc[numCommands] = f;
        numCommands++;
    }
    else
    {
        cerr << "[CLI Warning] Đã đạt giới hạn số lượng lệnh (" << CMD_MAX_NUM << ")" << endl;
    }
}

void CmdLineInterface::initCmd()
{
    // Lớp cơ sở - có thể ghi đè trong lớp kế thừa
}

void CmdLineInterface::initConsole()
{
    // Lớp cơ sở - có thể ghi đè trong lớp kế thừa
}

void CmdLineInterface::readCmd(string& cmd)
{
    if (!getline(cin, cmd))
    {
        cmd = CMD_QUIT_NAME;
    }
    if (!cmd.empty() && cmd.back() == '\r')
    {
        cmd.pop_back();
    }
}

unsigned short CmdLineInterface::parseCmd(const string& cmd, string cmd_argv[], int& cmd_argc)
{
    cmd_argc = 0;
    string cur = "";
    bool inQuotes = false;

    for (size_t i = 0; i < cmd.length(); i++)
    {
        char c = cmd[i];
        if (c == '\r')
        {
            continue;
        }
        if (c == '"')
        {
            inQuotes = !inQuotes;
        }
        else if (isspace(static_cast<unsigned char>(c)) && !inQuotes)
        {
            if (!cur.empty())
            {
                if (cmd_argc < CMD_MAX_ARG_NUM)
                {
                    cmd_argv[cmd_argc++] = cur;
                }
                cur.clear();
            }
        }
        else
        {
            cur += c;
        }
    }

    if (!cur.empty() && cmd_argc < CMD_MAX_ARG_NUM)
    {
        cmd_argv[cmd_argc++] = cur;
    }

    if (cmd_argc == 0)
    {
        return CMD_NOOP_ID;
    }

    string firstLower = cmd_argv[0];
    for (char& ch : firstLower)
    {
        ch = tolower(static_cast<unsigned char>(ch));
    }

    if (firstLower == CMD_QUIT_NAME || firstLower == "exit" || firstLower == "q")
    {
        return CMD_QUIT_ID;
    }

    for (unsigned short i = 0; i < numCommands; i++)
    {
        string registeredLower = cmdNameList[i];
        for (char& ch : registeredLower)
        {
            ch = tolower(static_cast<unsigned char>(ch));
        }
        if (firstLower == registeredLower)
        {
            return i;
        }
    }

    return CMD_UNKNOWN_ID;
}

void CmdLineInterface::doUnknown()
{
    cout << "Lệnh không hợp lệ. Gõ 'help' để xem danh sách các lệnh hỗ trợ." << endl;
}

void CmdLineInterface::doQuit()
{
    bRunning = false;
    cout << "Tạm biệt!" << endl;
}

void CmdLineInterface::doCmd(unsigned short id, string cmd_argv[], int cmd_argc)
{
    if (id < numCommands && cmdDoFunc[id] != nullptr)
    {
        (this->*cmdDoFunc[id])(cmd_argv, cmd_argc);
    }
}

void CmdLineInterface::run()
{
    initConsole();
    initCmd();
    bRunning = true;

    while (bRunning)
    {
        showCmdPrompt();
        string line;
        readCmd(line);

        string argv[CMD_MAX_ARG_NUM];
        int argc = 0;

        unsigned short id = parseCmd(line, argv, argc);
        if (id == CMD_QUIT_ID)
        {
            doQuit();
        }
        else if (id == CMD_UNKNOWN_ID)
        {
            doUnknown();
        }
        else if (id == CMD_NOOP_ID)
        {
            continue;
        }
        else
        {
            doCmd(id, argv, argc);
        }
    }
}

void CmdLineInterface::run(char* initArgv[], int initArgc)
{
    if (initArgc <= 1)
    {
        run();
        return;
    }

    initConsole();
    initCmd();

    string argv[CMD_MAX_ARG_NUM];
    int argc = 0;
    for (int i = 1; i < initArgc && argc < CMD_MAX_ARG_NUM; i++)
    {
        argv[argc++] = string(initArgv[i]);
    }

    if (argc > 0)
    {
        string firstLower = argv[0];
        for (char& ch : firstLower)
        {
            ch = tolower(static_cast<unsigned char>(ch));
        }

        if (firstLower == CMD_QUIT_NAME || firstLower == "exit" || firstLower == "q")
        {
            doQuit();
            return;
        }

        unsigned short foundId = CMD_UNKNOWN_ID;
        for (unsigned short i = 0; i < numCommands; i++)
        {
            string registeredLower = cmdNameList[i];
            for (char& ch : registeredLower)
            {
                ch = tolower(static_cast<unsigned char>(ch));
            }
            if (firstLower == registeredLower)
            {
                foundId = i;
                break;
            }
        }

        if (foundId != CMD_UNKNOWN_ID)
        {
            doCmd(foundId, argv, argc);
        }
        else
        {
            doUnknown();
        }
    }
}
