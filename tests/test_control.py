from __future__ import annotations

import json
import socket
import tempfile
import time
from pathlib import Path

import pytest

from krabville.control import ControlServer


def test_control_request_ids_are_idempotent() -> None:
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("Unix sockets are exercised on the Linux deployment target")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "control.sock"
        calls = 0

        def status(params):
            nonlocal calls
            calls += 1
            return {"value": params["value"]}

        server = ControlServer(path, {"status": status})
        thread = server.start()
        assert thread is not None
        deadline = time.monotonic() + 2
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)

        def request(value: int) -> dict:
            payload = json.dumps(
                {"id": "fixed-request", "op": "status", "params": {"value": value}}
            ).encode() + b"\n"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(path))
                client.sendall(payload)
                return json.loads(client.recv(4096).split(b"\n", 1)[0])

        try:
            assert request(1)["ok"] is True
            assert request(1)["ok"] is True
            conflict = request(2)
            assert conflict["ok"] is False
            assert conflict["error"] == "IdempotencyConflict"
            assert calls == 1
        finally:
            server.close()
            thread.join(timeout=2)
