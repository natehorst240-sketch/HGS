/* ptymodem: make a Linux pseudo-terminal look like a serial port with modem
 * control lines, for programs (Wine's serial layer) that need TIOCMGET et al.
 *
 * Wine's WaitCommEvent worker calls get_modem_status() before polling for
 * received bytes; on a pty TIOCMGET fails with ENOTTY and Wine cancels the
 * wait, so a Windows program using MSCOMM32 never sees EV_RXCHAR. This shim
 * intercepts ioctl(): when TIOCMGET/TIOCMSET/TIOCMBIS/TIOCMBIC fail with
 * ENOTTY on a tty it reports CTS, DSR and carrier asserted and accepts
 * control-line changes. Everything else passes straight through.
 *
 *   gcc -shared -fPIC -O2 -o ptymodem64.so ptymodem.c -ldl
 *   gcc -m32 -shared -fPIC -O2 -o ptymodem32.so ptymodem.c -ldl
 *   LD_PRELOAD=/path/ptymodem32.so wine program.exe
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdarg.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

typedef int (*ioctl_fn)(int, unsigned long, ...);

int ioctl(int fd, unsigned long request, ...)
{
    static ioctl_fn real;
    va_list ap;
    void *arg;
    int ret;

    if (!real) real = (ioctl_fn)dlsym(RTLD_NEXT, "ioctl");
    va_start(ap, request);
    arg = va_arg(ap, void *);
    va_end(ap);

    ret = real(fd, request, arg);
    if (ret == 0 || errno != ENOTTY || !isatty(fd)) return ret;

    switch (request) {
    case TIOCMGET:
        if (arg) *(int *)arg = TIOCM_CTS | TIOCM_DSR | TIOCM_CAR | TIOCM_DTR | TIOCM_RTS;
        return 0;
    case TIOCMSET:
    case TIOCMBIS:
    case TIOCMBIC:
        return 0;
    default:
        errno = ENOTTY;
        return ret;
    }
}
