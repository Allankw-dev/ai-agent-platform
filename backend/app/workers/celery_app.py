from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "agent_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    # The scheduler (`celery beat`, the `scheduler` service) looks for runs whose worker died.
    beat_schedule={
        "recover-stale-runs": {
            "task": "agents.recover_stale_runs",
            "schedule": float(settings.run_recovery_interval_seconds),
        }
    },
)
