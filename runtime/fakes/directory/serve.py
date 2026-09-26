"""Stub internal REST API - the employee directory.

Forty lines of stdlib standing in for a real internal service. It exists to prove that a
SECOND kind of shared connection goes through the identical broker: same entitlement
check, same audit record, different adapter.

    python runtime/fakes/directory/serve.py [port]
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PEOPLE = [
    {"email": "krishna@corp.example", "name": "Krishna Murari", "dept": "People Ops"},
    {"email": "sam@corp.example", "name": "Sam Whitfield", "dept": "People Analytics"},
    {"email": "raj@corp.example", "name": "Raj Mehta", "dept": "People Analytics"},
    {"email": "lena@corp.example", "name": "Lena Fischer", "dept": "Engineering"},
]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        if parsed.path not in ("/people", "/v1/people"):
            self.send_error(404, "no such resource")
            return
        wanted = parse_qs(parsed.query).get("dept", [None])[0]
        items = [p for p in PEOPLE if not wanted or p["dept"] == wanted]
        body = json.dumps({"items": items}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep test output readable
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    print(f"directory-api stub on http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
