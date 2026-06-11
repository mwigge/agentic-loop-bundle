#!/usr/bin/env python3
"""One-shot OTLP HTTP receiver used by the local integration check."""

from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        if self.path != "/v1/traces" or not body:
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        print(f"received {len(body)} bytes at {self.path}", flush=True)

    def log_message(self, *_: object) -> None:
        return


HTTPServer(("127.0.0.1", 4318), Handler).handle_request()
