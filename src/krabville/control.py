from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from .observability import log_event


MAX_BYTES = 16 * 1024


class ControlServer:
    def __init__(self, path: Path, operations: dict[str, Callable[[dict[str, Any]], Any]]):
        self.path = path
        self.operations = operations
        self._stop = threading.Event()
        self._socket: socket.socket | None = None
        self._responses: OrderedDict[str, tuple[str, dict[str, Any]]] = OrderedDict()

    def start(self) -> threading.Thread | None:
        if not hasattr(socket, "AF_UNIX"):
            return None
        thread = threading.Thread(target=self.serve, name="krabville-control", daemon=True)
        thread.start()
        return thread

    def close(self) -> None:
        self._stop.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def serve(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket = server
        server.bind(str(self.path))
        os.chmod(self.path, 0o660)
        server.listen(8)
        server.settimeout(1)
        while not self._stop.is_set():
            try:
                client, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with client:
                client.settimeout(5)
                raw = b""
                while b"\n" not in raw and len(raw) <= MAX_BYTES:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    raw += chunk
                response: dict[str, Any]
                request_id = None
                cacheable = False
                started = time.monotonic()
                operation = "unknown"
                try:
                    request = json.loads(raw.split(b"\n", 1)[0].decode("utf-8"))
                    request_id = str(request.get("id") or uuid.uuid4())
                    operation = str(request.get("op") or "")
                    params = request.get("params") if isinstance(request.get("params"), dict) else {}
                    fingerprint = json.dumps(
                        {"op": operation, "params": params},
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    cached = self._responses.get(request_id)
                    if cached:
                        if cached[0] != fingerprint:
                            response = {
                                "id": request_id,
                                "ok": False,
                                "error": "IdempotencyConflict",
                                "detail": "request id was already used with different parameters",
                            }
                        else:
                            response = cached[1]
                        client.sendall(
                            json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"
                        )
                        continue
                    handler = self.operations.get(operation)
                    if not handler:
                        raise ValueError("unsupported operation")
                    result = handler(params)
                    response = {"id": request_id, "ok": True, "result": result}
                    cacheable = True
                except Exception as error:
                    response = {"id": request_id, "ok": False, "error": type(error).__name__, "detail": str(error)[:240]}
                    cacheable = bool(request_id and "fingerprint" in locals())
                if cacheable and request_id:
                    self._responses[request_id] = (fingerprint, response)
                    self._responses.move_to_end(request_id)
                    while len(self._responses) > 128:
                        self._responses.popitem(last=False)
                log_event(
                    "engine",
                    "control_request",
                    request=request_id,
                    operation=operation,
                    status="complete" if response["ok"] else "failed",
                    elapsedMs=max(0, round((time.monotonic() - started) * 1000)),
                )
                client.sendall(json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n")
