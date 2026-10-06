"""Re-queue dead-letter jobs after fixing the underlying problem."""
from app.config import load_settings
from app.server import build_service

print("requeued:", build_service(load_settings()).queue.requeue_dead())
