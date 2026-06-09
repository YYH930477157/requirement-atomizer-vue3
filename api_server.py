from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DEFAULT_OUTPUT = Path("out/abnt_nbr_16968_atomizer_v5")


class RequirementAPIHandler(BaseHTTPRequestHandler):
    output_dir: Path = DEFAULT_OUTPUT

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/health":
            self.send_json({"ok": True, "service": "requirement-atomizer-api"})
            return
        if parsed.path == "/manifest":
            self.send_file_json("manifest.json")
            return
        if parsed.path == "/quality":
            self.send_file_json("quality_report.json")
            return
        if parsed.path == "/requirements":
            limit = parse_int(one(params, "limit"), default=50)
            requirement_type = one(params, "type")
            rows = read_jsonl(self.output_dir / "atomic_requirements.jsonl")
            if requirement_type:
                rows = [row for row in rows if row.get("requirement_type") == requirement_type]
            self.send_json(enrich_requirements(rows[:limit], self.output_dir))
            return
        if parsed.path == "/reviews":
            limit = parse_int(one(params, "limit"), default=50)
            self.send_json(read_jsonl(self.output_dir / "llm_review_results.jsonl")[:limit])
            return
        if parsed.path == "/review-states":
            limit = parse_int(one(params, "limit"), default=50)
            status = one(params, "status")
            rows = read_jsonl(self.output_dir / "review_states.jsonl")
            if status:
                rows = [row for row in rows if row.get("status") == status]
            self.send_json(rows[:limit])
            return
        if parsed.path == "/review-summary":
            self.send_json(build_review_summary(self.output_dir))
            return
        self.send_error(404, "Unknown endpoint")

    def send_file_json(self, filename: str) -> None:
        path = self.output_dir / filename
        if not path.exists():
            self.send_error(404, f"Missing file: {filename}")
            return
        self.send_json(json.loads(path.read_text(encoding="utf-8")))

    def send_json(self, payload, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format: str, *args) -> None:
        return


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def one(params: dict[str, list[str]], name: str) -> str:
    values = params.get(name) or [""]
    return values[0]


def parse_int(value: str, *, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def enrich_requirements(requirements: list[dict], output_dir: Path) -> list[dict]:
    reviews_by_requirement = {
        str(row.get("requirement_id")): row for row in read_jsonl(output_dir / "llm_review_results.jsonl") if row.get("requirement_id")
    }
    states_by_requirement = {
        str(row.get("requirement_id")): row for row in read_jsonl(output_dir / "review_states.jsonl") if row.get("requirement_id")
    }
    enriched: list[dict] = []
    for requirement in requirements:
        row = dict(requirement)
        req_id = str(row.get("req_id") or "")
        if req_id in reviews_by_requirement:
            row["review"] = reviews_by_requirement[req_id]
        if req_id in states_by_requirement:
            row["review_state"] = states_by_requirement[req_id]
        enriched.append(row)
    return enriched


def build_review_summary(output_dir: Path) -> dict:
    reviews = read_jsonl(output_dir / "llm_review_results.jsonl")
    states = read_jsonl(output_dir / "review_states.jsonl")
    decision_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for review in reviews:
        decision = str(review.get("decision") or "unknown")
        risk = str(review.get("risk") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
    for state in states:
        status = str(state.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "counts": {
            "reviews": len(reviews),
            "review_states": len(states),
        },
        "decision_counts": decision_counts,
        "risk_counts": risk_counts,
        "status_counts": status_counts,
        "files": {
            "llm_review_results": "llm_review_results.jsonl",
            "review_states": "review_states.jsonl",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve requirement atomizer output over a local HTTP API.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    RequirementAPIHandler.output_dir = args.out.expanduser().resolve()
    server = ThreadingHTTPServer((args.host, args.port), RequirementAPIHandler)
    print(json.dumps({"host": args.host, "port": args.port, "output_dir": str(RequirementAPIHandler.output_dir)}, indent=2))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
