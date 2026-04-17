"""Alerting webhook posts. No network: use a local HTTP stub."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar

import pytest

from claude_backup_cron import alerting


class _Handler(BaseHTTPRequestHandler):
    received: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            _Handler.received.append(json.loads(raw))
        except json.JSONDecodeError:
            _Handler.received.append({"_raw": raw})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_: Any, **__: Any) -> None:
        return


@pytest.fixture
def stub_server():  # type: ignore[no-untyped-def]
    _Handler.received.clear()
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_post_success(stub_server: HTTPServer) -> None:
    host, port = stub_server.server_address
    url = f"http://{host}:{port}/hook"
    assert alerting.post(url, "hello from test") is True
    assert _Handler.received[-1]["content"] == "hello from test"


def test_post_swallows_unreachable() -> None:
    # Port 1 is almost certainly not listening and not privileged to us;
    # post must return False rather than raise.
    assert alerting.post("http://127.0.0.1:1/nope", "x") is False


def test_post_empty_url_is_noop() -> None:
    assert alerting.post("", "x") is False


def test_post_truncates_long_message(stub_server: HTTPServer) -> None:
    host, port = stub_server.server_address
    url = f"http://{host}:{port}/hook"
    big = "x" * 5000
    assert alerting.post(url, big) is True
    assert len(_Handler.received[-1]["content"]) <= 1900
