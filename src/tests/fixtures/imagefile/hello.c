/* si#552's test file: `--version` prints `hello <VERSION>`, `--hang` never returns, `--net` says whether a
 * route to the outside exists (a UDP connect sends nothing), anything else echoes stdin to stdout. Built
 * twice by the Dockerfile beside it: static as /hello, dynamic as /hello-dynamic. */
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--version") == 0) {
        printf("hello %s\n", VERSION);
        return 0;
    }
    if (argc > 1 && strcmp(argv[1], "--hang") == 0) {
        for (;;)
            pause();
    }
    if (argc > 1 && strcmp(argv[1], "--net") == 0) {
        struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(9)};
        inet_pton(AF_INET, "192.0.2.1", &to.sin_addr); /* TEST-NET-1: routed nowhere, and nothing is sent */
        int s = socket(AF_INET, SOCK_DGRAM, 0);
        int routed = s >= 0 && connect(s, (struct sockaddr *)&to, sizeof to) == 0;
        printf("network: %s\n", routed ? "routed" : "unreachable");
        return 0;
    }
    char buf[4096];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, stdin)) > 0)
        fwrite(buf, 1, n, stdout);
    return 0;
}
