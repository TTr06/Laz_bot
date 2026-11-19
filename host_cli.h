#ifndef _HOST_CLI_H_
#define _HOST_CLI_H_

#include "cli.h"
#include <string>

using namespace std;

class HostCLI : public CmdLineInterface
{
public:
    HostCLI();
    HostCLI(const string& prompt);

protected:
    virtual void initCmd() override;
    virtual void initConsole() override;

private:
    // Các lệnh được kế thừa và gắn vào CmdLineInterface
    void cmdHelp(string argv[], int argc);
    void cmdPrices(string argv[], int argc);
    void cmdTargets(string argv[], int argc);
    void cmdSetPrice(string argv[], int argc);
    void cmdDelPrice(string argv[], int argc);
    void cmdCart(string argv[], int argc);
    void cmdTrack(string argv[], int argc);
    void cmdCookie(string argv[], int argc);
    void cmdBot(string argv[], int argc);
    void cmdDb(string argv[], int argc);
    void cmdClear(string argv[], int argc);

    // Tiện ích hỗ trợ
    void executeBackend(const string& cmdArgs);
    void printBanner();
};

#endif // _HOST_CLI_H_
