import asyncio
import uuid

from app.engine.executor import execute_run
from app.workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """Smoke-test task proving the worker can receive and run jobs."""
    return "pong"


# The hard limit sits above the platform's longest per-agent timeout (AGENT_TIMEOUT_CEILING_SECONDS,
# 300 by default) plus slack for loading and closing the run. The engine enforces each agent's own,
# shorter timeout itself.
@celery_app.task(name="agents.execute_run", time_limit=420, soft_time_limit=390)
def execute_run_task(run_id: str, org_id: str) -> None:
    """Run one queued agent run. Redelivery is safe: a run that is not queued is never rerun."""
    asyncio.run(execute_run(uuid.UUID(run_id), uuid.UUID(org_id)))
