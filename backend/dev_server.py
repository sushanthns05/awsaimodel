"""Local development server.

Simulates API Gateway in front of the same Lambda handlers used in AWS.
Run:  python backend/dev_server.py  (from the repository root)

Local defaults: file-backed store, mock AI provider, auth disabled but every
request still passes through the same RBAC code path.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("USE_LOCAL_STORE", "true")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("LOG_FORMAT", "text")
os.environ.setdefault("LOCAL_API_BASE", "http://127.0.0.1:8000")
os.environ.setdefault("CORS_ORIGIN", "*")

from backend.src.common.config import get_settings  # noqa: E402
from backend.src.documents.storage import get_storage  # noqa: E402
from backend.src.handlers import admin_api, intake  # noqa: E402

MAX_BODY = 12 * 1024 * 1024


class DevHandler(BaseHTTPRequestHandler):
    server_version = "SBGRecruitmentDev/1.0"

    def log_message(self, fmt: str, *args) -> None:  # quieter logs
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return ""
        return self.rfile.read(length).decode("utf-8") if length else ""

    def _event(self, body: str) -> dict:
        parsed = urllib.parse.urlparse(self.path)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        headers = {k.lower(): v for k, v in self.headers.items()}
        return {
            "version": "2.0",
            "rawPath": parsed.path,
            "rawQueryString": parsed.query,
            "headers": headers,
            "queryStringParameters": query,
            "requestContext": {
                "http": {"method": self.command, "path": parsed.path, "sourceIp": self.client_address[0]},
                "requestId": f"local-{id(self)}",
                "stage": "local",
            },
            "body": body,
            "isBase64Encoded": False,
        }

    def _send(self, response: dict) -> None:
        self.send_response(int(response.get("statusCode", 200)))
        for key, value in (response.get("headers") or {}).items():
            if key.lower() not in ("content-length", "connection"):
                self.send_header(key, value)
        body = response.get("body") or ""
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _dispatch(self, handler) -> None:
        body = self._read_body()
        self._send(handler(self._event(body), None))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._dispatch(admin_api.lambda_handler)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/dev/files/"):
            self._serve_file()
            return
        self._dispatch(admin_api.lambda_handler)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0].rstrip("/") == "/intake":
            self._dispatch(intake.lambda_handler)
            return
        self._dispatch(admin_api.lambda_handler)

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch(admin_api.lambda_handler)

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch(admin_api.lambda_handler)

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch(admin_api.lambda_handler)

    def _serve_file(self) -> None:
        settings = get_settings()
        storage = get_storage()
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path.split("/", 4)
        if len(parts) < 5:
            self.send_error(404)
            return
        bucket, encoded_key = parts[3], parts[4]
        key = urllib.parse.unquote(encoded_key)
        if bucket not in (settings.resume_bucket, settings.report_bucket):
            self.send_error(403)
            return
        try:
            data = storage.get_bytes(bucket, key)
        except Exception:  # noqa: BLE001
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{Path(key).name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), DevHandler)
    print(f"SBG recruitment API running at http://127.0.0.1:{port}")
    print("Local mode: file-backed store, mock AI, auth bypassed via AUTH_DISABLED=true")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
