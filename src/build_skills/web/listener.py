"""Reserve a loopback port and hand the same socket to the HTTP server."""

import errno
import socket
from collections.abc import Sequence


def bind_listener(ports: Sequence[int]) -> socket.socket:
    for port in ports:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(socket.SOMAXCONN)
            return listener
        except OSError as exc:
            listener.close()
            if exc.errno != errno.EADDRINUSE:
                raise
    raise OSError(errno.EADDRINUSE, f"端口被占用：{', '.join(map(str, ports))} 均不可用")
