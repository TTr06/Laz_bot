#include "host_cli.h"

int main(int argc, char* argv[])
{
    HostCLI cli("LazBot> ");
    cli.run(argv, argc);
    return 0;
}
