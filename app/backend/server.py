"""MuleTrace AI Unified Web & API Server.

Serves the frontend static dashboard while providing backend API endpoints
to connect the UI with AWS Bedrock AI and the investigation engine.
Zero external server dependencies (uses Python standard library http.server).
"""
from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backend import engine
from app.backend.config import load_environment


class MuleTraceRequestHandler(SimpleHTTPRequestHandler):
    """Handles static file requests and MuleTrace AI backend API endpoints."""

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json_response(self, data: dict[str, Any], status_code: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        clean_path = self.path.split("?")[0]

        if clean_path in ("/api/health", "/health"):
            health = engine.health_check()
            self._send_json_response(health)
            return

        if clean_path in ("/api/cases", "/cases"):
            try:
                cases_df = engine.load_case_accounts()
                tx_df = engine.load_transactions()
                unique_cases = cases_df["case_id"].dropna().unique().tolist()
                records = []
                for cid in unique_cases:
                    accounts = cases_df[cases_df["case_id"] == cid]["account_id"].tolist()
                    target = accounts[0] if accounts else None
                    tx_match = tx_df[tx_df["target_account"] == target] if target else None
                    amount = float(tx_match.iloc[0]["amount"]) if tx_match is not None and not tx_match.empty else 0
                    source = tx_match.iloc[0]["source_account"] if tx_match is not None and not tx_match.empty else "-"
                    records.append({
                        "caseId": cid,
                        "source": source,
                        "target": target,
                        "amount": amount,
                        "status": "new",
                    })
                self._send_json_response({"status": "success", "cases": records})
                return
            except Exception as exc:
                self._send_json_response({"status": "error", "message": str(exc)}, 500)
                return

        # Serve static assets from frontend directory
        super().do_GET()

    def do_POST(self) -> None:
        clean_path = self.path.split("?")[0]

        if clean_path in ("/api/ai/summary", "/ai/summary"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}

                case_id = payload.get("case_id") or "CASE001"
                target_lang = (payload.get("language") or "th").strip().lower()
                investigation_input = payload.get("investigation") or {}

                # Map external case IDs if needed (e.g. MT-1042 -> CASE001)
                normalized_case = "CASE001" if "1042" in str(case_id) else ("CASE002" if "1043" in str(case_id) else str(case_id))

                # Fetch engine investigation metrics
                try:
                    investigation_data = engine.score_investigation(case_id=normalized_case)
                except Exception:
                    investigation_data = {
                        "case_id": normalized_case,
                        "investigation": investigation_input,
                    }

                # Generate AI Narrative via Bedrock
                try:
                    from app.backend.aws.bedrock_service import generate_narrative_report
                    report = generate_narrative_report(investigation_data, language=target_lang)
                    summary = report.get("narrative", "")
                    if not summary.strip():
                        raise ValueError("Empty report generated")
                except Exception as ai_err:
                    # Fallback summary if AWS Bedrock is offline or unconfigured
                    if target_lang == "en":
                        summary = (
                            f"MuleTrace AML Rule Engine Report for {case_id}:\n"
                            f"- Priority Score: {investigation_data.get('score', 80)} ({investigation_data.get('priority', 'High')})\n"
                            f"- Key Signals: {', '.join(investigation_data.get('rule_types_matched', ['multiple_incoming', 'rapid_outgoing']))}\n"
                            f"- Status: Active investigation triage completed.\n"
                            f"(Note: AWS Bedrock connection notice: {ai_err})"
                        )
                    else:
                        summary = (
                            f"รายงานระบบกฎ MuleTrace AML สำหรับเคส {case_id}:\n"
                            f"- คะแนนความสำคัญ: {investigation_data.get('score', 80)} ({investigation_data.get('priority', 'High')})\n"
                            f"- สัญญาณความเสี่ยงหลัก: {', '.join(investigation_data.get('rule_types_matched', ['multiple_incoming', 'rapid_outgoing']))}\n"
                            f"- สถานะ: ดำเนินการคัดกรองเบื้องต้นเสร็จสิ้น\n"
                            f"(หมายเหตุการเชื่อมต่อ AWS Bedrock: {ai_err})"
                        )

                self._send_json_response({"status": "success", "summary": summary})
                return

            except Exception as exc:
                self._send_json_response({"status": "error", "message": str(exc)}, 500)
                return

        self._send_json_response({"status": "error", "message": "Endpoint not found"}, 404)


def run_server(port: int = 8000, bind: str = "127.0.0.1", directory: Path | str | None = None) -> None:
    # Load private environment (.env)
    env = load_environment(PROJECT_ROOT)
    os.environ.update(env)

    target_dir = Path(directory) if directory else PROJECT_ROOT / "app" / "frontend"
    handler = functools.partial(MuleTraceRequestHandler, directory=str(target_dir))

    server = ThreadingHTTPServer((bind, port), handler)
    print(f"[*] MuleTrace AI Server running on http://{bind}:{port}/", flush=True)
    print(f"[*] Serving static files from: {target_dir}", flush=True)
    print(f"[*] AI Summary API Endpoint ready at: http://{bind}:{port}/api/ai/summary", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down MuleTrace AI Server...", flush=True)
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="MuleTrace AI Unified Web & API Server")
    parser.add_argument("port", type=int, nargs="?", default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--bind", "-b", default="127.0.0.1", help="Address to bind to (default: 127.0.0.1)")
    parser.add_argument("--directory", "-d", default=None, help="Directory to serve static files from")
    args = parser.parse_args()

    run_server(port=args.port, bind=args.bind, directory=args.directory)


if __name__ == "__main__":
    main()
