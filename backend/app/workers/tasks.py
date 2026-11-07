from app.workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """Smoke-test task proving the worker can receive and run jobs."""
    return "pong"
