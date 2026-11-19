#ifndef _CLI_H_
#define _CLI_H_

#include <string>

using namespace std;

class CmdLineInterface;

typedef void (CmdLineInterface::*CLI_CMD_FUNC)(string[], int);

#define CLI_CAST(p_func_type) static_cast<CLI_CMD_FUNC>(p_func_type)

const unsigned short CMD_MAX_NUM = 64;
const unsigned short CMD_MAX_ARG_NUM = 16;

const unsigned short CMD_NOOP_ID  =  CMD_MAX_NUM + 1;
const unsigned short CMD_UNKNOWN_ID = CMD_MAX_NUM;
const unsigned short CMD_QUIT_ID = CMD_MAX_NUM + 3;

const string CMD_QUIT_NAME = "quit";

class CmdLineInterface
{
private:
    string cmdPrompt;
    CLI_CMD_FUNC cmdDoFunc[CMD_MAX_NUM];
    bool bRunning;
    unsigned short numCommands;
    string cmdNameList[CMD_MAX_NUM];

protected:
    unsigned int cmdDefaulID;

public:
    CmdLineInterface();
    CmdLineInterface(const string& prompt);
    void setCmdPrompt(const string& prompt);
    void clearScreen();
    void showCmdPrompt();
    void addCmd(const string& name, CLI_CMD_FUNC f);
    void run(); // run without initial arguments
    void run(char* initArgv[], int initArgc); // run with initial arguments

protected:
    virtual void initCmd();
    virtual void initConsole();

private:
    void readCmd(string& cmd);
    unsigned short parseCmd(const string& cmd, string cmd_argv[], int& cmd_argc);
    void doUnknown();
    void doQuit();
    void doCmd(unsigned short id, string cmd_argv[], int cmd_argc);
};

#endif // _CLI_H_
