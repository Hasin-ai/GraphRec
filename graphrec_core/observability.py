"""ER-NF-09: structured logs and Prometheus metrics (no extra dependency).

Logs
    ``configure_logging()`` installs a JSON formatter (``LOG_FORMAT=json``, the
    production default) that adds the request's correlation id to every record.

Metrics
    Each API process counts requests per (method, route template, status) and a
    latency histogram per route in memory and flushes the deltas to Redis every few
    seconds, so ``/metrics`` reports the sum over all API processes. Without Redis
    the endpoint still answers with this process's own counts and says so
    (``graphrec_metrics_shared 0``). Route *templates* are used as labels, never raw
    paths, so tenant ids and product ids never become label values.
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from collections import Counter
from datetime import datetime, timezone

correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)

STANDARD_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
REDIS_KEY = "graphrec:metrics:v1"
FLUSH_SECONDS = 5.0


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation = getattr(record, "correlation_id", None) or correlation_id_var.get()
        if correlation:
            entry["correlation_id"] = str(correlation)
        for key in ("method", "route", "status", "duration_ms", "event"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(log_format: str, level: str = "INFO") -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if log_format == "json" else
                         logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    # Access lines come from the request log below, with correlation ids.
    logging.getLogger("uvicorn.access").disabled = True


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Counter[str] = Counter()
        self._local: Counter[str] = Counter()
        self._client = None
        self._last_flush = time.monotonic()
        self._started = time.time()

    def bind_redis(self, client) -> None:  # noqa: ANN001
        self._client = client

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        # Arbitrary request methods must not become label values (unbounded series).
        method = method if method in STANDARD_METHODS else "OTHER"
        klass = f"{status // 100}xx"
        fields = [f"req|{method}|{route}|{klass}", f"sum|{route}", f"count|{route}"]
        with self._lock:
            self._pending[fields[0]] += 1
            self._pending[fields[2]] += 1
            self._pending[fields[1]] += int(seconds * 1_000_000)  # microseconds, integer for HINCRBY
            for bound in BUCKETS:
                if seconds <= bound:
                    self._pending[f"bucket|{route}|{bound}"] += 1
            due = time.monotonic() - self._last_flush >= FLUSH_SECONDS
        if due:
            self.flush()

    def flush(self) -> bool:
        with self._lock:
            pending, self._pending = self._pending, Counter()
            self._last_flush = time.monotonic()
        if not pending:
            return True
        if self._client is not None:
            try:
                pipe = self._client.pipeline(transaction=False)
                for field, value in pending.items():
                    pipe.hincrby(REDIS_KEY, field, value)
                pipe.execute()
                return True
            except Exception:  # noqa: BLE001 - metrics must never break requests
                pass
        with self._lock:
            self._local.update(pending)
        return False

    def snapshot(self) -> tuple[dict[str, int], bool]:
        self.flush()
        if self._client is not None:
            try:
                raw = self._client.hgetall(REDIS_KEY)
                return {k.decode() if isinstance(k, bytes) else k: int(v) for k, v in raw.items()}, True
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            return dict(self._local), False

    def render(self, aggregates: dict | None, extra: dict[str, float]) -> str:
        data, shared = self.snapshot()
        lines = ["# HELP graphrec_http_requests_total HTTP requests by method, route template and status class.",
                 "# TYPE graphrec_http_requests_total counter"]
        routes = set()
        for field, value in sorted(data.items()):
            parts = field.split("|")
            if parts[0] == "req" and len(parts) == 4:
                _, method, route, klass = parts
                routes.add(route)
                lines.append(f'graphrec_http_requests_total{{method="{method}",route="{_escape(route)}",status="{klass}"}} {value}')
        lines += ["# HELP graphrec_http_request_duration_seconds Request latency by route template.",
                  "# TYPE graphrec_http_request_duration_seconds histogram"]
        for route in sorted({f.split("|")[1] for f in data if f.startswith("count|")}):
            r = _escape(route)
            for bound in BUCKETS:
                lines.append(f'graphrec_http_request_duration_seconds_bucket{{route="{r}",le="{bound}"}} {data.get(f"bucket|{route}|{bound}", 0)}')
            count = data.get(f"count|{route}", 0)
            lines.append(f'graphrec_http_request_duration_seconds_bucket{{route="{r}",le="+Inf"}} {count}')
            lines.append(f'graphrec_http_request_duration_seconds_sum{{route="{r}"}} {data.get(f"sum|{route}", 0) / 1_000_000:.6f}')
            lines.append(f'graphrec_http_request_duration_seconds_count{{route="{r}"}} {count}')
        lines += ["# HELP graphrec_metrics_shared 1 when counters are summed across API processes through Redis.",
                  "# TYPE graphrec_metrics_shared gauge", f"graphrec_metrics_shared {int(shared)}"]
        if aggregates is not None:
            names = {"training_queued": ("graphrec_training_jobs", 'status="queued"'),
                     "training_running": ("graphrec_training_jobs", 'status="running"'),
                     "tenants_active": ("graphrec_tenants", 'status="active"'),
                     "tenants_suspended": ("graphrec_tenants", 'status="suspended"'),
                     "active_model_versions": ("graphrec_active_model_versions", "")}
            seen = set()
            for key, (metric, label) in names.items():
                if metric not in seen:
                    lines += [f"# TYPE {metric} gauge"]
                    seen.add(metric)
                lines.append(f"{metric}{{{label}}} {aggregates.get(key, 0)}" if label else f"{metric} {aggregates.get(key, 0)}")
        for name, value in extra.items():
            lines += [f"# TYPE {name} gauge", f"{name} {value}"]
        return "\n".join(lines) + "\n"


METRICS = Metrics()
