from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlparse

from review_actions import apply_review_action
from llm_client import LLMConnectionError, LLMResponseError, chat_json
from llm_pipeline import DEFAULT_PIPELINE_PATH, llm_config_from_route, load_review_pipeline


DEFAULT_OUTPUT = Path("out/abnt_nbr_16968_atomizer_v5")
DEFAULT_ALLOWED_ORIGINS = {"http://127.0.0.1:8770", "http://localhost:8770", "null"}
TOKEN_HEADER = "X-Requirement-Atomizer-Token"


class RequirementAPIHandler(BaseHTTPRequestHandler):
    output_dir: Path = DEFAULT_OUTPUT
    allowed_origins: set[str] = set(DEFAULT_ALLOWED_ORIGINS)
    local_token: str = ""

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        if not is_allowed_origin(origin, self.allowed_origins):
            self.send_error(403, "Origin not allowed")
            return
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        origin = self.headers.get("Origin", "")
        if not is_allowed_origin(origin, self.allowed_origins):
            self.send_error(403, "Origin not allowed")
            return
        if parsed.path == "/health":
            self.send_json({"ok": True, "service": "requirement-atomizer-api"})
            return
        if not token_is_valid(self.local_token, self.headers, params):
            self.send_json({"error": "unauthorized"}, status=401)
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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        origin = self.headers.get("Origin", "")
        if not is_allowed_origin(origin, self.allowed_origins):
            self.send_error(403, "Origin not allowed")
            return
        if not self.local_token or not token_is_valid(self.local_token, self.headers, params):
            self.send_json({"error": "unauthorized"}, status=401)
            return
        if parsed.path == "/translations":
            self.handle_translation()
            return
        if parsed.path != "/review-actions":
            self.send_error(404, "Unknown endpoint")
            return

        payload = self.read_json_body()
        if payload is None:
            return
        requirement_id = str(payload.get("requirement_id") or "").strip()
        status = str(payload.get("status") or "").strip()
        actor = str(payload.get("actor") or "").strip() or None
        reason = str(payload.get("reason") or "").strip()
        if not requirement_id or not status:
            self.send_json({"error": "requirement_id and status are required"}, status=400)
            return
        try:
            state = apply_review_action(self.output_dir, requirement_id, status, actor=actor, reason=reason)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=409)
            return
        self.send_json(state)

    def handle_translation(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            return
        requirement_id = str(payload.get("requirement_id") or "").strip()
        text = str(payload.get("text") or "").strip()
        if not text:
            self.send_json({"error": "text is required"}, status=400)
            return
        try:
            translation = translate_requirement_text(text, requirement_id=requirement_id, output_dir=self.output_dir)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return
        except (LLMConnectionError, LLMResponseError) as exc:
            self.send_json({"error": str(exc)}, status=502)
            return
        self.send_json({"requirement_id": requirement_id, "translation": translation})

    def read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"error": "invalid content length"}, status=400)
            return None
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "invalid json body"}, status=400)
            return None
        if not isinstance(payload, dict):
            self.send_json({"error": "json body must be an object"}, status=400)
            return None
        return payload

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
        origin = self.headers.get("Origin", "")
        if origin and is_allowed_origin(origin, self.allowed_origins):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif "null" in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {TOKEN_HEADER}")

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


def is_allowed_origin(origin: str, allowed_origins: set[str]) -> bool:
    if not origin:
        return True
    if origin == "file://" or origin.startswith("file://"):
        return True
    return origin in allowed_origins


def token_is_valid(expected_token: str, headers: Mapping[str, str], params: dict[str, list[str]]) -> bool:
    if not expected_token:
        return True
    header_token = headers.get(TOKEN_HEADER, "")
    return header_token == expected_token


def enrich_requirements(requirements: list[dict], output_dir: Path) -> list[dict]:
    reviews_by_requirement = index_by_requirement_identity(read_jsonl(output_dir / "llm_review_results.jsonl"))
    states_by_requirement = index_by_requirement_identity(read_jsonl(output_dir / "review_states.jsonl"))
    enriched: list[dict] = []
    for requirement in requirements:
        row = dict(requirement)
        for key in requirement_identity_keys(row):
            if key in reviews_by_requirement:
                row["review"] = reviews_by_requirement[key]
                break
        for key in requirement_identity_keys(row):
            if key in states_by_requirement:
                row["review_state"] = states_by_requirement[key]
                break
        enriched.append(row)
    return enriched


def index_by_requirement_identity(rows: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        for key in requirement_identity_keys(row):
            indexed[key] = row
    return indexed


def requirement_identity_keys(row: dict) -> list[str]:
    keys: list[str] = []
    for name in ("stable_req_id", "requirement_id", "req_id"):
        value = row.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    for name in ("stable_req_id", "req_id"):
        value = metadata.get(name)
        if value:
            text = str(value)
            if text not in keys:
                keys.append(text)
    return keys


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


TRANSLATION_SYSTEM_PROMPT = """You are a technical translator for DLMS/COSEM requirements.
Translate English requirement text into concise Simplified Chinese.
Preserve identifiers, quoted service names, OBIS codes, class names, attribute names, and protocol acronyms.
Return only JSON with one string field: translation."""


def translate_requirement_text(text: str, *, requirement_id: str = "", output_dir: Path | None = None) -> str:
    pipeline = load_review_pipeline(DEFAULT_PIPELINE_PATH)
    route_payload = dict(pipeline.model_routes.get("openai_compatible") or {})
    config = llm_config_from_route(route_payload)
    payload = chat_json(
        config,
        TRANSLATION_SYSTEM_PROMPT,
        json.dumps(
            {
                "requirement_id": requirement_id,
                "text": text,
            },
            ensure_ascii=False,
        ),
    )
    translation = str(payload.get("translation") or "").strip()
    if not translation:
        raise LLMResponseError("LLM translation response missing translation")
    return translation


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve requirement atomizer output over a local HTTP API.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="Allowed browser Origin. Can be provided multiple times.",
    )
    parser.add_argument("--token", default="", help="Optional local API token required for data endpoints.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    RequirementAPIHandler.output_dir = args.out.expanduser().resolve()
    RequirementAPIHandler.allowed_origins = build_allowed_origins(args.host, args.port, args.allow_origin)
    RequirementAPIHandler.local_token = args.token
    server = ThreadingHTTPServer((args.host, args.port), RequirementAPIHandler)
    print(
        json.dumps(
            {
                "host": args.host,
                "port": args.port,
                "output_dir": str(RequirementAPIHandler.output_dir),
                "allowed_origins": sorted(RequirementAPIHandler.allowed_origins),
                "token_required": bool(RequirementAPIHandler.local_token),
            },
            indent=2,
        ),
        flush=True,
    )
    server.serve_forever()
    return 0


def build_allowed_origins(host: str, port: int, extra_origins: list[str]) -> set[str]:
    origins = {"null", f"http://{host}:{port}", f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    origins.update(origin for origin in extra_origins if origin)
    return origins


if __name__ == "__main__":
    raise SystemExit(main())
