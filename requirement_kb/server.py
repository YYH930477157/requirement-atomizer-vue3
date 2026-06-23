from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .cli import default_kb_paths
from .repository import KnowledgeRepository


class KBRequestHandler(BaseHTTPRequestHandler):
    repo: KnowledgeRepository

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/health":
            self.send_json({"ok": True})
            return
        if parsed.path == "/info":
            self.send_json(self.repo.info())
            return
        if parsed.path == "/search":
            query = one(params, "q")
            self.send_json(
                self.repo.search(
                    query,
                    layer=one(params, "layer") or None,
                    entry_type=one(params, "type") or None,
                    limit=int(one(params, "limit") or 20),
                )
            )
            return
        if parsed.path == "/get":
            entry_id = one(params, "entry_id")
            self.send_json(self.repo.get(entry_id, kb_id=one(params, "kb_id") or None))
            return
        self.send_error(404, "Unknown endpoint")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload = self.read_json()
        if parsed.path == "/match":
            self.send_json(
                self.repo.match_text(
                    str(payload.get("text", "")),
                    layer=payload.get("layer"),
                    entry_type=payload.get("type"),
                    limit=int(payload.get("limit", 50)),
                )
            )
            return
        if parsed.path == "/context":
            self.send_json(self.repo.export_context(str(payload.get("text", "")), limit=int(payload.get("limit", 20))))
            return
        self.send_error(404, "Unknown endpoint")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_json(self, payload, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args) -> None:
        return


def one(params: dict[str, list[str]], name: str) -> str:
    values = params.get(name) or [""]
    return values[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve knowledge base query API over local HTTP.")
    parser.add_argument("--kb", type=Path, action="append", default=[], help="Knowledge base JSON file. Can be repeated.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = KnowledgeRepository.from_paths(args.kb or default_kb_paths())
    KBRequestHandler.repo = repo
    server = ThreadingHTTPServer((args.host, args.port), KBRequestHandler)
    print(json.dumps({"host": args.host, "port": args.port, "knowledge_bases": repo.info()}, ensure_ascii=False, indent=2))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
