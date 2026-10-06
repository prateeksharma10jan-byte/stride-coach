"""Run the job worker as its own process (set RUN_WORKER=0 on the web process)."""
import threading

from app.config import load_settings
from app.jobs import Worker
from app.observability import init_sentry, setup_logging
from app.server import build_service

s = load_settings()
setup_logging(s.log_json)
init_sentry(s.sentry_dsn)
svc = build_service(s)
Worker(svc.queue, svc.handlers()).run_forever(threading.Event())
