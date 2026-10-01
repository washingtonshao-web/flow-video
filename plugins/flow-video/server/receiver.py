"""Tiny loopback receiver: the Flow tab POSTs a finished clip here and it is written straight into the job folder.

Avoids Chrome's download pipeline (and its multiple-download blocking). Started by server.py on demand.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = 8765
_server = None


class _H(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin.endswith(".google.com") or origin.endswith(".google") or origin.startswith("https://flow.google"):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        q = parse_qs(urlparse(self.path).query)
        job, name = Path(q["job"][0]), Path(q["name"][0]).name
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n)
        ok = (job / "job.json").exists() and name.endswith((".mp4", ".png", ".jpg"))
        if ok:
            (job / "clips").mkdir(exist_ok=True)
            (job / "clips" / name).write_bytes(data)
        self.send_response(200 if ok else 400)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": ok, "bytes": len(data)}).encode())

    def log_message(self, *a):
        pass


def ensure_running(port: int = PORT) -> int:
    global _server
    if _server is None:
        try:
            _server = ThreadingHTTPServer(("127.0.0.1", port), _H)
        except OSError:
            return port          # another server instance already listening
        threading.Thread(target=_server.serve_forever, daemon=True).start()
    return port


if __name__ == "__main__":
    ensure_running()
    print("listening", PORT)
    threading.Event().wait()
