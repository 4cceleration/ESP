import os, sys, time, termios, fcntl, struct, select
PORT = "/dev/cu.usbserial-0001"
baud = int(sys.argv[1]) if len(sys.argv) > 1 else 115200
reset = (len(sys.argv) > 2 and sys.argv[2] == "reset")
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 5
fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
a = termios.tcgetattr(fd)
a[0] = 0; a[1] = 0; a[3] = 0
a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
a[4] = a[5] = getattr(termios, "B%d" % baud)
a[6][termios.VMIN] = 0; a[6][termios.VTIME] = 0
termios.tcsetattr(fd, termios.TCSANOW, a)
def setline(bit, on):
    fcntl.ioctl(fd, termios.TIOCMBIS if on else termios.TIOCMBIC, struct.pack("I", bit))
if reset:
    setline(termios.TIOCM_DTR, False)   # GPIO0 high -> normal boot
    setline(termios.TIOCM_RTS, True)    # EN low
    time.sleep(0.15)
    termios.tcflush(fd, termios.TCIFLUSH)
    setline(termios.TIOCM_RTS, False)   # EN high -> run
else:
    setline(termios.TIOCM_DTR, False); setline(termios.TIOCM_RTS, False)
end = time.time() + secs
buf = b""
while time.time() < end:
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try: buf += os.read(fd, 4096)
        except BlockingIOError: pass
os.close(fd)
sys.stdout.write("".join(ch if (32 <= ord(ch) < 127 or ch in "\n\t") else "" for ch in buf.decode("latin-1").replace("\r", "")))
print("\n[bytes: %d]" % len(buf))
