"""Observability: structured JSON logging and Prometheus metrics for Reel storefront.

Provides:
- ContextVar-based X-Correlation-ID propagation in logs.
- Multi-worker Redis-backed Prometheus /metrics endpoint (no extra heavy library).
- Route template labels (no high-cardinality item or session IDs).
- Metrics for HTTP requests, GraphRec call latencies, fallback strategies,
  telemetry feedback errors, and rate limits.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

correlation_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("correlation_id", default=None)

STANDARD_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
REDIS_METRICS_KEY = "reel:metrics:v1"
FLUSH_SECONDS = 5.0


class JsonFormatter(logging.Formatter):
    """Outputs structured JSON log records with correlation ID and request context."""

    def format(self, record: logging.LogRecord) -> str:
        entry: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        cid = getattr(record, "correlation_id", None) or correlation_id_var.get()
        if cid:
            entry["correlation_id"] = str(cid)

        for key in ("method", "route", "status", "duration_ms", "event", "shopper", "shelf"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)

        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(log_format: str = "json", level: str = "INFO") -> None:
    """Configures application logging with JSON or text format."""
    root = logging.getLogger()
    handler = logging.StreamHandler()
    if log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    root.handlers[:] = [handler]
    root.setLevel(level.upper())

    # Keep uvicorn errors in the stream, but avoid duplicated access logs
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class ReelMetrics:
    """Collects counters and histograms, flushing to Redis across uvicorn workers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Counter[str] = Counter()
        self._local: Counter[str] = Counter()
        self._redis = None
        self._last_flush = time.monotonic()
        self._started = time.time()

    def bind_redis(self, client: Any) -> None:
        self._redis = client

    def observe_http(self, method: str, route: str, status: int, seconds: float) -> None:
        method = method if method in STANDARD_METHODS else "OTHER"
        klass = f"{status // 100}xx"
        with self._lock:
            self._pending[f"req|{method}|{route}|{klass}"] += 1
            self._pending[f"http_count|{route}"] += 1
            self._pending[f"http_sum|{route}"] += int(seconds * 1_000_000)
            for bound in BUCKETS:
                if seconds <= bound:
                    self._pending[f"http_bucket|{route}|{bound}"] += 1
            due = time.monotonic() - self._last_flush >= FLUSH_SECONDS
        if due:
            self.flush()

    def observe_graphrec(self, endpoint: str, outcome: str, seconds: float) -> None:
        outcome = "success" if outcome == "success" else "error"
        with self._lock:
            self._pending[f"gr_req|{endpoint}|{outcome}"] += 1
            self._pending[f"gr_count|{endpoint}"] += 1
            self._pending[f"gr_sum|{endpoint}"] += int(seconds * 1_000_000)
            for bound in BUCKETS:
                if seconds <= bound:
                    self._pending[f"gr_bucket|{endpoint}|{bound}"] += 1
            due = time.monotonic() - self._last_flush >= FLUSH_SECONDS
        if due:
            self.flush()

    def observe_fallback(self, strategy: str) -> None:
        with self._lock:
            self._pending[f"fallback|{strategy}"] += 1

    def observe_feedback_failure(self, kind: str) -> None:
        with self._lock:
            self._pending[f"fb_failure|{kind}"] += 1

    def observe_rate_limit_hit(self) -> None:
        with self._lock:
            self._pending["rate_limit_hit"] += 1

    def flush(self) -> bool:
        with self._lock:
            pending, self._pending = self._pending, Counter()
            self._last_flush = time.monotonic()

        if not pending:
            return True

        if self._redis is not None:
            try:
                pipe = self._redis.pipeline(transaction=False)
                for field, value in pending.items():
                    pipe.hincrby(REDIS_METRICS_KEY, field, value)
                pipe.execute()
                return True
            except Exception:
                pass

        with self._lock:
            self._local.update(pending)
        return False

    def snapshot(self) -> Tuple[Dict[str, int], bool]:
        self.flush()
        if self._redis is not None:
            try:
                raw = self._redis.hgetall(REDIS_METRICS_KEY)
                data = {k: int(v) for k, v in raw.items()}
                return data, True
            except Exception:
                pass
        with self._lock:
            return dict(self._local), False

    def render(self) -> str:
        data, shared = self.snapshot()
        lines = [
            "# HELP reel_http_requests_total HTTP requests by method, route and status class.",
            "# TYPE reel_http_requests_total counter",
        ]
        for field, value in sorted(data.items()):
            parts = field.split("|")
            if parts[0] == "req" and len(parts) == 4:
                _, method, route, klass = parts
                lines.append(f'reel_http_requests_total{{method="{method}",route="{_escape(route)}",status="{klass}"}} {value}')

        lines += [
            "# HELP reel_http_request_duration_seconds HTTP request latency by route template.",
            "# TYPE reel_http_request_duration_seconds histogram",
        ]
        http_routes = sorted({f.split("|")[1] for f in data if f.startswith("http_count|")})
        for route in http_routes:
            r = _escape(route)
            for bound in BUCKETS:
                lines.append(f'reel_http_request_duration_seconds_bucket{{route="{r}",le="{bound}"}} {data.get(f"http_bucket|{route}|{bound}", 0)}')
            count = data.get(f"http_count|{route}", 0)
            lines.append(f'reel_http_request_duration_seconds_bucket{{route="{r}",le="+Inf"}} {count}')
            lines.append(f'reel_http_request_duration_seconds_sum{{route="{r}"}} {data.get(f"http_sum|{route}", 0) / 1_000_000:.6f}')
            lines.append(f'reel_http_request_duration_seconds_count{{route="{r}"}} {count}')

        lines += [
            "# HELP reel_graphrec_calls_total Calls made to GraphRec backend.",
            "# TYPE reel_graphrec_calls_total counter",
        ]
        for field, value in sorted(data.items()):
            parts = field.split("|")
            if parts[0] == "gr_req" and len(parts) == 3:
                _, endpoint, outcome = parts
                lines.append(f'reel_graphrec_calls_total{{endpoint="{_escape(endpoint)}",outcome="{outcome}"}} {value}')

        lines += [
            "# HELP reel_graphrec_duration_seconds GraphRec API call latency.",
            "# TYPE reel_graphrec_duration_seconds histogram",
        ]
        gr_endpoints = sorted({f.split("|")[1] for f in data if f.startswith("gr_count|")})
        for ep in gr_endpoints:
            e = _escape(ep)
            for bound in BUCKETS:
                lines.append(f'reel_graphrec_duration_seconds_bucket{{endpoint="{e}",le="{bound}"}} {data.get(f"gr_bucket|{ep}|{bound}", 0)}')
            count = data.get(f"gr_count|{ep}", 0)
            lines.append(f'reel_graphrec_duration_seconds_bucket{{endpoint="{e}",le="+Inf"}} {count}')
            lines.append(f'reel_graphrec_duration_seconds_sum{{endpoint="{e}"}} {data.get(f"gr_sum|{ep}", 0) / 1_000_000:.6f}')
            lines.append(f'reel_graphrec_duration_seconds_count{{endpoint="{e}"}} {count}')

        lines += [
            "# HELP reel_fallbacks_total Fallback recommendation executions.",
            "# TYPE reel_fallbacks_total counter",
        ]
        for field, value in sorted(data.items()):
            if field.startswith("fallback|"):
                strategy = field.split("|", 1)[1]
                lines.append(f'reel_fallbacks_total{{strategy="{_escape(strategy)}"}} {value}')

        lines += [
            "# HELP reel_feedback_errors_total Failed telemetry feedback deliveries.",
            "# TYPE reel_feedback_errors_total counter",
        ]
        for field, value in sorted(data.items()):
            if field.startswith("fb_failure|"):
                kind = field.split("|", 1)[1]
                lines.append(f'reel_feedback_errors_total{{kind="{_escape(kind)}"}} {value}')

        lines += [
            "# HELP reel_rate_limit_hits_total Number of times requests were rate limited (429).",
            "# TYPE reel_rate_limit_hits_total counter",
            f"reel_rate_limit_hits_total {data.get('rate_limit_hit', 0)}",
            "# HELP reel_metrics_shared 1 when counters are shared across processes via Redis.",
            "# TYPE reel_metrics_shared gauge",
            f"reel_metrics_shared {int(shared)}",
        ]

        return "\n".join(lines) + "\n"


METRICS = ReelMetrics()
