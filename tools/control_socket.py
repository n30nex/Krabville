#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import uuid
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation")
    parser.add_argument("--socket", type=Path, default=Path("/run/canadaverse-control/krabville/control.sock"))
    parser.add_argument("--params", default="{}")
    args = parser.parse_args()
    request = {
        "id": str(uuid.uuid4()),
        "op": args.operation,
        "params": json.loads(args.params),
    }
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > 16 * 1024:
        raise SystemExit("request is too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10)
        client.connect(str(args.socket))
        client.sendall(payload)
        response = b""
        while b"\n" not in response and len(response) <= 16 * 1024:
            block = client.recv(4096)
            if not block:
                break
            response += block
    print(json.dumps(json.loads(response.split(b"\n", 1)[0]), indent=2))


if __name__ == "__main__":
    main()
