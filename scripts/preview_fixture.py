"""Serve local test pages without a reverse hostname lookup.

HTTPServer normally calls socket.getfqdn before listening. That lookup can
stall on hosted macOS runners; a numeric loopback fixture needs no hostname.
"""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer, test
from socketserver import TCPServer


class LocalHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", type=int)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()
    test(
        HandlerClass=SimpleHTTPRequestHandler,
        ServerClass=LocalHTTPServer,
        port=args.port,
        bind=args.bind,
    )


if __name__ == "__main__":
    main()
