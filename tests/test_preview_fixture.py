"""The local HTTP fixture must listen without waiting for hostname resolution."""

import importlib.util
import socket
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

import pytest


def test_loopback_fixture_binds_without_hostname_resolution(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "preview_fixture.py"
    spec = importlib.util.spec_from_file_location("preview_fixture", path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)

    def forbidden(*args, **kwargs):
        pytest.fail("A numeric loopback fixture tried to resolve a hostname")

    monkeypatch.setattr(socket, "getfqdn", forbidden)
    with fixture.LocalHTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler) as server:
        address = server.server_address
        assert server.server_name == "127.0.0.1"
        assert server.server_port == address[1]
        with socket.create_connection(address, timeout=1):
            pass
