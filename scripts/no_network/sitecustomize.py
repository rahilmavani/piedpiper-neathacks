"""Put on PYTHONPATH (scripts/demo_replay.sh does) to forbid internet access in that Python process.

Connecting an IPv4/IPv6 socket or resolving a host name raises, so a replay that tried to reach a
model provider or neatlogs fails loudly instead of quietly spending money or exporting traces.
Local sockets (AF_UNIX) still work.
"""

import socket


class NetworkBlocked(OSError):
    pass


_INET = (socket.AF_INET, socket.AF_INET6)
_connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex


def _guard(self: socket.socket, address: object) -> None:
    if self.family in _INET:
        raise NetworkBlocked(f"network access is blocked here (tried {address!r})")


def _blocked_connect(self, address):
    _guard(self, address)
    return _connect(self, address)


def _blocked_connect_ex(self, address):
    _guard(self, address)
    return _connect_ex(self, address)


def _blocked_getaddrinfo(host, *args, **kwargs):
    raise NetworkBlocked(f"network access is blocked here (tried to resolve {host!r})")


socket.socket.connect = _blocked_connect
socket.socket.connect_ex = _blocked_connect_ex
socket.getaddrinfo = _blocked_getaddrinfo
