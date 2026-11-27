"""Writes a run's progress to the database as it happens.

Every call opens its own short transaction and commits, so a person watching the run sees each
step as soon as it finishes, and a crash never loses what was already recorded. The tenant context
is the organization only (a worker acts for the organization, not for a user).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.tenancy import use_tenant
from app.engine.pricing import micro_to_usd
from app.models.enums import ApprovalStatus, RunEventType, RunStatus, StepStatus, StepType
from app.models.runs import AgentRun, Approval, RunStep
from app.models.usage import UsageRecord
from app.repositories import approvals as approval_repo
from app.repositories import run_events
from app.services import audit

MAX_TEXT_CHARS = 20_000
MAX_REASONING_CHARS = 1_000


def strip_nul(value: Any) -> Any:
    """Remove NUL characters (which JSONB rejects) without changing anything else.

    Unlike `scrub` this never shortens text, so it is safe for data that must come back exactly as
    it went in: the arguments of an action a person approves, and the saved conversation.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {str(strip_nul(k)): strip_nul(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [strip_nul(v) for v in value]
    return value


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


class RunSuperseded(Exception):  # noqa: N818 (a signal, not an error to report)
    """Another worker has taken this run over; this one must stop without writing anything more.

    Raised when a worker's attempt number no longer matches the run's. Every write the recorder
    makes checks it first (fencing), so a worker that merely stalled, say through a long pause of
    its host, cannot go on running a run that a new worker has already recovered.
    """


@dataclass(frozen=True)
class StartedCall:
    """The step for one tool call. `existing` is set when that call was already started before."""

    step_id: uuid.UUID
    existing: RunStep | None = None


class RunRecorder:
    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        *,
        org_id: uuid.UUID,
        run_id: uuid.UUID,
        agent_id: uuid.UUID,
        attempt: int = 1,
    ) -> None:
        self._maker = maker
        self._org_id = org_id
        self._run_id = run_id
        self._agent_id = agent_id
        self._attempt = attempt

    async def _guard(self, session: AsyncSession) -> None:
        """Refuse to write if another worker now holds this run (see RunSuperseded)."""
        current = await session.scalar(select(AgentRun.attempt).where(AgentRun.id == self._run_id))
        if current is not None and current != self._attempt:
            raise RunSuperseded

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
        call_key: str | None = None,
    ) -> uuid.UUID:
        async with self._session() as session:
            await self._guard(session)
            step = await self._add_step(
                session,
                step_type,
                name=name,
                tool_key=tool_key,
                input=input,
                call_key=call_key,
            )
            await session.commit()
            return step.id

    async def start_tool_step(
        self,
        call_key: str | None,
        *,
        name: str,
        tool_key: str,
        input: dict[str, Any] | None = None,
    ) -> StartedCall:
        """Start the step for one tool call, or return the one that already exists.

        A call key names one tool call of one model reply and is unique within the run in the
        database itself, so however many workers or deliveries reach the same call, only one can
        start it; the others get the existing step back and decide from its state (replay its
        result, or stop) instead of running the tool again.
        """
        if call_key is None:
            return StartedCall(
                await self.start_step(StepType.TOOL_CALL, name=name, tool_key=tool_key, input=input)
            )
        async with self._session() as session:
            await self._guard(session)
            existing = await session.scalar(
                select(RunStep).where(RunStep.run_id == self._run_id, RunStep.call_key == call_key)
            )
            if existing is not None:
                return StartedCall(existing.id, existing)
            try:
                async with session.begin_nested():
                    step = await self._add_step(
                        session,
                        StepType.TOOL_CALL,
                        name=name,
                        tool_key=tool_key,
                        input=input,
                        call_key=call_key,
                    )
            except IntegrityError:
                # Lost a race with another worker that started the same call a moment earlier.
                session.expire_all()
                existing = await session.scalar(
                    select(RunStep).where(
                        RunStep.run_id == self._run_id, RunStep.call_key == call_key
                    )
                )
                if existing is None:
                    raise
                return StartedCall(existing.id, existing)
            await session.commit()
            return StartedCall(step.id)

    async def get_step(self, step_id: uuid.UUID) -> RunStep | None:
        async with self._session() as session:
            return await session.scalar(select(RunStep).where(RunStep.id == step_id))

    async def pending_approval_id(self, step_id: uuid.UUID) -> uuid.UUID | None:
        """The approval still waiting for a decision on this step, if there is one."""
        async with self._session() as session:
            return await session.scalar(
                select(Approval.id).where(
                    Approval.run_step_id == step_id, Approval.status == ApprovalStatus.PENDING
                )
            )

    async def _add_step(
        self,
        session: AsyncSession,
        step_type: StepType,
        *,
        name: str | None,
        tool_key: str | None,
        input: dict[str, Any] | None,
        call_key: str | None,
    ) -> RunStep:
        """Add a step and announce it, inside the caller's transaction (the caller commits)."""
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
            call_key=call_key,
        )
        session.add(step)
        await session.flush()
        await run_events.emit(
            session,
            self._run_id,
            RunEventType.STEP_STARTED,
            {
                "step_id": str(step.id),
                "sequence": step.sequence,
                "step_type": step_type.value,
                "tool_key": tool_key,
            },
        )
        return step

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
            await self._guard(session)
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
            await run_events.emit(
                session,
                self._run_id,
                RunEventType.STEP_FINISHED,
                {"step_id": str(step_id), "status": status.value},
            )
            await session.commit()

    async def request_approval(
        self,
        *,
        step_id: uuid.UUID,
        tool_key: str,
        proposed_input: dict[str, Any],
        reasoning_summary: str | None,
        expires_at: datetime,
    ) -> uuid.UUID:
        """Ask a person to approve an action, and mark its step as waiting for the decision.

        `proposed_input` is stored exactly (never shortened): it is what the person sees, and it is
        what runs if they approve.
        """
        reason = strip_nul(reasoning_summary)[:MAX_REASONING_CHARS] if reasoning_summary else None
        async with self._session() as session:
            await self._guard(session)
            approval = await approval_repo.create(
                session,
                org_id=self._org_id,
                run_id=self._run_id,
                run_step_id=step_id,
                tool_key=tool_key,
                proposed_input=strip_nul(proposed_input),
                reasoning_summary=reason or None,
                expires_at=expires_at,
            )
            await session.execute(
                update(RunStep)
                .where(RunStep.id == step_id)
                .values(status=StepStatus.AWAITING_APPROVAL)
            )
            await audit.record(
                session,
                org_id=self._org_id,
                actor_id=None,
                action="approval.requested",
                resource_type="approval",
                resource_id=approval.id,
                details={"run_id": str(self._run_id), "tool_key": tool_key},
            )
            await run_events.emit(
                session,
                self._run_id,
                RunEventType.APPROVAL_REQUESTED,
                {"approval_id": str(approval.id), "step_id": str(step_id), "tool_key": tool_key},
            )
            await session.commit()
            return approval.id

    async def mark_step_running(self, step_id: uuid.UUID) -> bool:
        """Mark an approved action as started. False if it was not waiting any more.

        This is written before the action runs, so if the worker dies mid-action the run can say
        plainly that it is unknown whether the action happened (and never retries it).
        """
        async with self._session() as session:
            await self._guard(session)
            result = await session.execute(
                update(RunStep)
                .where(RunStep.id == step_id, RunStep.status == StepStatus.AWAITING_APPROVAL)
                .values(status=StepStatus.RUNNING)
                .returning(RunStep.id)
            )
            started = result.first() is not None
            await session.commit()
            return started

    async def record_usage(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_micro_usd: int,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        """One usage row per model call, and running totals on the run itself.

        `checkpoint`, if given, is saved in the same transaction, so what a model call cost and
        where the loop stands afterwards are never recorded without each other.
        """
        cost = micro_to_usd(cost_micro_usd)
        async with self._session() as session:
            await self._guard(session)
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
            if checkpoint is not None:
                await self._write_progress(session, checkpoint)
            await session.commit()

    async def _write_progress(self, session: AsyncSession, checkpoint: dict[str, Any]) -> None:
        """Save the loop's state on the run, but only while this worker still holds it."""
        await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == self._run_id,
                AgentRun.attempt == self._attempt,
                AgentRun.status == RunStatus.RUNNING,
            )
            .values(checkpoint=checkpoint)
        )

    async def save_progress(self, checkpoint: dict[str, Any]) -> None:
        """Save where the loop stands, so a replacement worker can carry on from here."""
        async with self._session() as session:
            await self._guard(session)
            await self._write_progress(session, checkpoint)
            await session.commit()

    async def heartbeat(self) -> bool:
        """Say this worker is alive. False means the run is no longer this worker's to run."""
        async with self._session() as session:
            result = await session.execute(
                update(AgentRun)
                .where(AgentRun.id == self._run_id, AgentRun.attempt == self._attempt)
                .values(heartbeat_at=func.now())
                .returning(AgentRun.id)
            )
            alive = result.first() is not None
            await session.commit()
            return alive

    async def is_cancelled(self) -> bool:
        """Whether the run was cancelled. Raises RunSuperseded if another worker holds it now."""
        async with self._session() as session:
            row = (
                await session.execute(
                    select(AgentRun.status, AgentRun.attempt).where(AgentRun.id == self._run_id)
                )
            ).first()
            if row is None:
                return False
            if row[1] != self._attempt:
                raise RunSuperseded
            return bool(row[0] is RunStatus.CANCELLED)
