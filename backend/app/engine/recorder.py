"""Writes a run's progress to the database as it happens.

Every call opens its own short transaction and commits, so a person watching the run sees each
step as soon as it finishes, and a crash never loses what was already recorded. The tenant context
is the organization only (a worker acts for the organization, not for a user).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.tenancy import use_tenant
from app.engine.pricing import micro_to_usd
from app.models.enums import RunStatus, StepStatus, StepType
from app.models.runs import AgentRun, RunStep
from app.models.usage import UsageRecord

MAX_TEXT_CHARS = 20_000


def scrub(value: Any) -> Any:
    """Make a value safe for a JSONB column: no NUL characters, bounded string length."""
    if isinstance(value, str):
        cleaned = value.replace("\x00", "")
        if len(cleaned) > MAX_TEXT_CHARS:
            return cleaned[:MAX_TEXT_CHARS] + "…[truncated]"
        return cleaned
    if isinstance(value, dict):
        return {str(scrub(k)): scrub(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value]
    return value


class RunRecorder:
    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        *,
        org_id: uuid.UUID,
        run_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> None:
        self._maker = maker
        self._org_id = org_id
        self._run_id = run_id
        self._agent_id = agent_id

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        async with self._maker() as session:
            await use_tenant(session, org_id=self._org_id)
            yield session

    async def start_step(
        self,
        step_type: StepType,
        *,
        name: str | None = None,
        tool_key: str | None = None,
        input: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        async with self._session() as session:
            sequence = await session.scalar(
                select(func.coalesce(func.max(RunStep.sequence), -1) + 1).where(
                    RunStep.run_id == self._run_id
                )
            )
            step = RunStep(
                org_id=self._org_id,
                run_id=self._run_id,
                sequence=int(sequence or 0),
                step_type=step_type,
                status=StepStatus.RUNNING,
                name=name,
                tool_key=tool_key,
                input=scrub(input) if input is not None else None,
            )
            session.add(step)
            await session.commit()
            return step.id

    async def finish_step(
        self,
        step_id: uuid.UUID,
        status: StepStatus,
        *,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        async with self._session() as session:
            await session.execute(
                update(RunStep)
                .where(RunStep.id == step_id)
                .values(
                    status=status,
                    output=scrub(output) if output is not None else None,
                    error=scrub(error) if error is not None else None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finished_at=func.now(),
                )
            )
            await session.commit()

    async def record_usage(
        self, *, model: str, input_tokens: int, output_tokens: int, cost_micro_usd: int
    ) -> None:
        """One usage row per model call, and running totals on the run itself."""
        cost = micro_to_usd(cost_micro_usd)
        async with self._session() as session:
            session.add(
                UsageRecord(
                    org_id=self._org_id,
                    run_id=self._run_id,
                    agent_id=self._agent_id,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                )
            )
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == self._run_id)
                .values(
                    input_tokens=AgentRun.input_tokens + input_tokens,
                    output_tokens=AgentRun.output_tokens + output_tokens,
                    cost_usd=AgentRun.cost_usd + cost,
                )
            )
            await session.commit()

    async def is_cancelled(self) -> bool:
        async with self._session() as session:
            status = await session.scalar(
                select(AgentRun.status).where(AgentRun.id == self._run_id)
            )
            return status is RunStatus.CANCELLED
