import asyncio
import uuid

from app.engine.executor import execute_run, resume_run
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
    """Run one queued agent run. Redelivery is safe: a run that is not queued is never rerun, and
    one delivered while its worker has died is taken over instead (see engine/recovery.py)."""
    asyncio.run(execute_run(uuid.UUID(run_id), uuid.UUID(org_id)))


@celery_app.task(name="agents.recover_stale_runs", time_limit=120, soft_time_limit=100)
def recover_stale_runs_task() -> dict[str, int]:
    """Take over runs whose worker has died (run every few seconds by the scheduler, see
    celery_app.beat_schedule). Safe to repeat or overlap: each run is decided under a row lock,
    so only one caller can ever take any one run."""
    return asyncio.run(_recover_stale_runs())


async def _recover_stale_runs() -> dict[str, int]:
    from app.db.session import standalone_sessionmaker
    from app.engine.recovery import recover_stale_runs
    from app.services.runs import celery_dispatcher

    async with standalone_sessionmaker() as maker:
        return await recover_stale_runs(maker, dispatch=celery_dispatcher)


@celery_app.task(name="agents.resume_run", time_limit=420, soft_time_limit=390)
def resume_run_task(run_id: str, org_id: str) -> None:
    """Continue a run that was waiting for a person's decision.

    Safe to repeat: only one call can claim the run, and the rest do nothing.
    """
    asyncio.run(resume_run(uuid.UUID(run_id), uuid.UUID(org_id)))
