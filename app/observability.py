"""Structured JSON logs, optional Sentry, Prometheus-style metrics text."""
from __future__ import annotations

import json
import logging
import time
from datetime import date


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": round(record.created, 3), "level": record.levelname,
               "logger": record.name, "msg": record.getMessage()}
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out)


def setup_logging(json_logs: bool = True, level=logging.INFO) -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter() if json_logs else
                   logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)


def init_sentry(dsn: str) -> bool:
    if not dsn:
        return False
    try:
        import sentry_sdk  # optional dependency
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0, send_default_pii=False)
        return True
    except ImportError:
        logging.getLogger("stride").warning("SENTRY_DSN set but sentry-sdk not installed")
        return False


def metrics_text(db, queue) -> str:
    c = queue.counts()
    lines = ["# TYPE stride_jobs gauge"]
    lines += [f'stride_jobs{{status="{k}"}} {v}' for k, v in sorted(c.items())]
    lines += ["# TYPE stride_users gauge", f"stride_users {db.user_count()}",
              "# TYPE stride_llm_calls_today gauge",
              f"stride_llm_calls_today {db.total_llm_calls(date.today().isoformat())}",
              "# TYPE stride_up gauge", f"stride_up 1", f"stride_scrape_ts {int(time.time())}"]
    return "\n".join(lines) + "\n"
