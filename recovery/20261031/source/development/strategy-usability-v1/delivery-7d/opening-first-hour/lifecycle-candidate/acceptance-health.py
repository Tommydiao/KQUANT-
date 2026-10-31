"""TEST_ONLY loopback health child; no KQUANT imports, databases or providers."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"test_only":true,"worker_ready":false}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 49152 <= args.port <= 65535:
        raise SystemExit("TEST_ONLY_EPHEMERAL_PORT_REQUIRED")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
