"""标准库 HTTP JSON 接口。

启动演示实例：``PYTHONPATH=src python -m basin_review.api --demo --port 8000``

主要端点：
- ``POST /api/runs``                        生成计算版本 {window_start, window_end, boundary_id, rule_version?}
- ``GET  /api/runs/{id}``                   计算版本明细（叠加评审状态）
- ``POST /api/runs/{id}/recompute``         按原口径复算校验
- ``GET  /api/runs/{a}/diff/{b}``           版本间差异归因
- ``GET  /api/portfolio/synergy?run_id=``   组合协同收益
- ``GET  /api/portfolio/conflicts``         冲突项
- ``GET  /api/portfolio/pending?run_id=``   尚待核实的数据
- ``GET  /api/portfolio/boundary-diff?...`` 边界对比与归因
- ``POST /api/reviews``                     评审 {result_key, decision, note?, reviewer?}
- ``POST /api/monitoring``                  登记/补齐监测 {reach_id, pollutant, month, load, source?}
- ``POST /api/baselines``                   登记新基准版本 {reach_id, pollutant, monthly_load, span_start, span_end, version, permit_ref?}
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .models import MonthSpan
from .service import BasinService


def _jsonable(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"不可序列化: {type(obj)!r}")


class Api:
    """把 HTTP 请求映射到 :class:`BasinService` 的薄层。"""

    def __init__(self, service: BasinService) -> None:
        self.service = service
        self.routes = [
            ("GET", re.compile(r"^/api/health$"), self.health),
            ("GET", re.compile(r"^/api/runs$"), self.list_runs),
            ("POST", re.compile(r"^/api/runs$"), self.create_run),
            ("GET", re.compile(r"^/api/runs/([^/]+)$"), self.get_run),
            ("POST", re.compile(r"^/api/runs/([^/]+)/recompute$"), self.recompute),
            ("GET", re.compile(r"^/api/runs/([^/]+)/diff/([^/]+)$"), self.diff),
            ("GET", re.compile(r"^/api/portfolio/synergy$"), self.synergy),
            ("GET", re.compile(r"^/api/portfolio/conflicts$"), self.conflicts),
            ("GET", re.compile(r"^/api/portfolio/pending$"), self.pending),
            ("GET", re.compile(r"^/api/portfolio/boundary-diff$"), self.boundary_diff),
            ("POST", re.compile(r"^/api/reviews$"), self.review),
            ("POST", re.compile(r"^/api/monitoring$"), self.monitoring),
            ("POST", re.compile(r"^/api/baselines$"), self.baselines),
        ]

    # -- 端点 ------------------------------------------------------------

    def health(self, query, body):
        return {"status": "ok"}

    def list_runs(self, query, body):
        return {"runs": sorted(self.service.runs)}

    def create_run(self, query, body):
        run = self.service.create_run(
            MonthSpan(body["window_start"], body["window_end"]),
            body["boundary_id"],
            body.get("rule_version"),
        )
        return {"run_id": run.id}

    def get_run(self, query, body, run_id):
        return self.service.run_view(run_id)

    def recompute(self, query, body, run_id):
        return self.service.recompute(run_id)

    def diff(self, query, body, run_a, run_b):
        return self.service.compare_runs(run_a, run_b)

    def synergy(self, query, body):
        return self.service.portfolio_synergy(query["run_id"][0])

    def conflicts(self, query, body):
        return {"conflicts": self.service.portfolio_conflicts()}

    def pending(self, query, body):
        return self.service.portfolio_pending(query["run_id"][0])

    def boundary_diff(self, query, body):
        return self.service.compare_boundaries(
            MonthSpan(query["window_start"][0], query["window_end"][0]),
            query["boundary_a"][0],
            query["boundary_b"][0],
            query.get("rule_version", [None])[0],
        )

    def review(self, query, body):
        return self.service.review(
            body["result_key"],
            body["decision"],
            body.get("note", ""),
            body.get("reviewer", ""),
        )

    def monitoring(self, query, body):
        record = self.service.add_monitoring(
            body["reach_id"], body["pollutant"], body["month"],
            body["load"], body.get("source", ""),
        )
        return {"recorded_seq": record.recorded_seq}

    def baselines(self, query, body):
        baseline = self.service.revise_baseline(
            body["reach_id"], body["pollutant"], body["monthly_load"],
            MonthSpan(body["span_start"], body["span_end"]),
            body["version"], body.get("permit_ref", ""), body.get("note", ""),
        )
        return {"recorded_seq": baseline.recorded_seq, "version": baseline.version}

    # -- 分发 --------------------------------------------------------------

    def dispatch(self, method: str, raw_path: str, body: dict):
        parsed = urlparse(raw_path)
        query = parse_qs(parsed.query)
        for route_method, pattern, handler in self.routes:
            if route_method != method:
                continue
            match = pattern.match(parsed.path)
            if match:
                try:
                    payload = handler(query, body, *match.groups())
                except (KeyError, ValueError) as exc:
                    return 400, {"error": str(exc)}
                # JSON 往返，保证返回内容与实际 HTTP 响应一致
                return 200, json.loads(
                    json.dumps(payload, ensure_ascii=False, default=_jsonable)
                )
        return 404, {"error": f"未找到路由: {method} {parsed.path}"}


def make_handler(service: BasinService):
    api = Api(service)

    class Handler(BaseHTTPRequestHandler):
        def _handle(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = {}
            if length:
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    self._respond(400, {"error": "请求体不是合法 JSON"})
                    return
            try:
                status, payload = api.dispatch(method, self.path, body)
            except (KeyError, ValueError) as exc:
                status, payload = 400, {"error": str(exc)}
            self._respond(status, payload)

        def _respond(self, status: int, payload) -> None:
            data = json.dumps(payload, ensure_ascii=False, default=_jsonable).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = lambda self: self._handle("GET")  # noqa: E731
        do_POST = lambda self: self._handle("POST")  # noqa: E731

        def log_message(self, *args):  # 静默访问日志
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="流域协同评估后端")
    parser.add_argument("--demo", action="store_true", help="载入演示数据")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.demo:
        from .demo import build_demo_service

        service = build_demo_service()
    else:
        service = BasinService()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    print(f"评估后端已启动: http://127.0.0.1:{args.port}/api/health")
    server.serve_forever()


if __name__ == "__main__":
    main()
