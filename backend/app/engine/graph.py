"""The agent loop, as a LangGraph state graph.

    START -> call_model --(tool calls requested)--> run_tools -> call_model ...
                  |                                    |
                  |                                    +--(an action needs a person)--> END (paused)
                  +--(finished, or a limit/error was hit)--> END

    START --(resuming after a person decided)--> run_tools

`call_model` checks the run's limits before spending anything, then asks the model for its next
move. `run_tools` executes each requested tool after validating it, one at a time. Every model
call and tool call is recorded as a run step as it happens.

Tool arguments come from the model and are never trusted: unknown tools, tools the agent was not
granted, arguments that break the schema, slow handlers and crashing handlers each end in an error
result that is fed back to the model, never in an action.

Actions that need a person: after the arguments pass validation (so a person is never asked about
nonsense), the engine records an approval holding those exact arguments, marks the step as waiting,
and ends this stretch of the graph. The executor saves the loop's state as a checkpoint and the run
waits, holding no worker. When a person decides, a new stretch starts at `run_tools`:
**approved** runs the stored arguments exactly as shown (never asking the model again) and
**rejected** tells the model that a person said no. Remaining tool calls from the same reply then
continue, and may pause again.
"""

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

from app.core.model_price import ModelPrice
from app.engine.limits import EffectiveLimits
from app.engine.llm import (
    FinishReason,
    LLMClient,
    LLMError,
    ToolCall,
    assistant_message,
    tool_message,
    user_message,
)
from app.engine.pricing import cost_micro_usd
from app.engine.recorder import MAX_TEXT_CHARS, RunRecorder, scrub, strip_nul
from app.models.enums import StepStatus, StepType
from app.tools import get_handler, prepare_arguments
from app.tools.base import ToolContext, ToolDefinition, ToolError, validate_arguments

log = structlog.get_logger()

CHECKPOINT_VERSION = 1
REJECTED_TEXT = "A person rejected this action, so it was not run."
CANCELLED_STEP = "The run was cancelled before this action ran."
CHANGED_ACTION = "The action no longer matches what was approved, so it was not run."


class Outcome(StrEnum):
    COMPLETED = "completed"
    EMPTY = "empty"
    TRUNCATED = "truncated"
    REFUSED = "refused"
    LLM_ERROR = "llm_error"
    ITERATION_LIMIT = "iteration_limit"
    TOOL_CALL_LIMIT = "tool_call_limit"
    TOKEN_LIMIT = "token_limit"  # noqa: S105 (an outcome label, not a secret)
    COST_LIMIT = "cost_limit"
    CANCELLED = "cancelled"
    AWAITING_APPROVAL = "awaiting_approval"


class EngineState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    # Results of this reply's tool calls that already ran, in order (kept across a pause).
    collected_results: list[dict[str, Any]]
    iterations: int
    # Tool calls attempted so far (a call that waited for approval counts once). Checkpoints saved
    # before this counter existed read it as 0.
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    final_text: str
    outcome: str  # an Outcome value once the loop has finished; empty while it is running
    error: str
    # The tool call waiting for a person: {approval_id, call_id, name, tool_key, step_id}.
    awaiting: dict[str, Any]
    # Set only when resuming: {awaiting, decision, note, arguments}.
    resume: dict[str, Any] | None


@dataclass(frozen=True)
class EngineConfig:
    model: str
    system: str
    max_output_tokens: int | None
    limits: EffectiveLimits
    prices: dict[str, ModelPrice]
    # How long a person has to decide before an approval request expires.
    approval_ttl: timedelta = timedelta(hours=24)


@dataclass(frozen=True)
class EngineDeps:
    llm: LLMClient
    recorder: RunRecorder
    tools: list[ToolDefinition]
    config: EngineConfig
    context: ToolContext


@dataclass(frozen=True)
class ToolOutcome:
    """What running one tool call produced, for the model."""

    text: str
    is_error: bool


@dataclass(frozen=True)
class Paused:
    """A tool call that needs a person before it can run."""

    awaiting: dict[str, Any]


def initial_state(message: str) -> EngineState:
    return {
        "messages": [user_message(message)],
        "pending_tool_calls": [],
        "collected_results": [],
        "iterations": 0,
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_micro_usd": 0,
        "final_text": "",
        "outcome": "",
        "error": "",
        "awaiting": {},
        "resume": None,
    }


def checkpoint_from_state(state: EngineState) -> dict[str, Any]:
    """The loop's state as plain JSON, saved on the run while it waits for a person.

    The arguments of the waiting action are deliberately not copied here: the approval row is the
    one place they live, so what a person approved is exactly what runs.
    """
    checkpoint: dict[str, Any] = {
        "version": CHECKPOINT_VERSION,
        "messages": state["messages"],
        "pending_tool_calls": state.get("pending_tool_calls", []),
        "collected_results": state.get("collected_results", []),
        "iterations": state["iterations"],
        "tool_calls": state.get("tool_calls", 0),
        "input_tokens": state["input_tokens"],
        "output_tokens": state["output_tokens"],
        "cost_micro_usd": state["cost_micro_usd"],
        "final_text": state.get("final_text", ""),
        "awaiting": state["awaiting"],
    }
    cleaned: dict[str, Any] = strip_nul(checkpoint)
    return cleaned


def state_from_checkpoint(
    checkpoint: dict[str, Any], *, decision: str, note: str | None, arguments: dict[str, Any]
) -> EngineState:
    """Rebuild the loop's state to continue after a person's decision."""
    if checkpoint.get("version") != CHECKPOINT_VERSION:
        raise ValueError("The saved state of this run has an unknown format.")
    return {
        "messages": checkpoint["messages"],
        "pending_tool_calls": checkpoint["pending_tool_calls"],
        "collected_results": checkpoint["collected_results"],
        "iterations": checkpoint["iterations"],
        "tool_calls": checkpoint.get("tool_calls", 0),
        "input_tokens": checkpoint["input_tokens"],
        "output_tokens": checkpoint["output_tokens"],
        "cost_micro_usd": checkpoint["cost_micro_usd"],
        "final_text": checkpoint.get("final_text", ""),
        "outcome": "",
        "error": "",
        "awaiting": checkpoint["awaiting"],
        "resume": {
            "awaiting": checkpoint["awaiting"],
            "decision": decision,
            "note": note,
            "arguments": arguments,
        },
    }


def recursion_limit(limits: EffectiveLimits) -> int:
    """LangGraph counts every node visit; one iteration is a model node plus a tools node."""
    return 2 * limits.max_iterations + 5


def _tool_result_text(result: dict[str, Any]) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS] + "…[truncated]"
    return text


def build_graph(deps: EngineDeps) -> Any:
    by_llm_name: dict[str, ToolDefinition] = {}
    for tool in deps.tools:
        if tool.llm_name in by_llm_name:
            raise ValueError(f"Two tools share the model-facing name {tool.llm_name!r}.")
        by_llm_name[tool.llm_name] = tool
    tool_specs = [tool.for_llm() for tool in deps.tools]
    config, recorder = deps.config, deps.recorder

    async def stop_reason(state: EngineState) -> Outcome | None:
        limits = config.limits
        if await recorder.is_cancelled():
            return Outcome.CANCELLED
        if state["iterations"] >= limits.max_iterations:
            return Outcome.ITERATION_LIMIT
        if state["input_tokens"] + state["output_tokens"] >= limits.max_total_tokens:
            return Outcome.TOKEN_LIMIT
        budget = limits.cost_budget_micro_usd
        if budget is not None and state["cost_micro_usd"] >= budget:
            return Outcome.COST_LIMIT
        return None

    async def call_model(state: EngineState) -> dict[str, Any]:
        reason = await stop_reason(state)
        if reason is not None:
            return {"outcome": reason.value}

        step_id = await recorder.start_step(
            StepType.LLM_CALL,
            name=config.model,
            input={"model": config.model, "messages": len(state["messages"])},
        )
        try:
            response = await deps.llm.complete(
                model=config.model,
                system=config.system,
                messages=state["messages"],
                tools=tool_specs,
                max_output_tokens=config.max_output_tokens,
            )
        except LLMError as exc:
            await recorder.finish_step(step_id, StepStatus.FAILED, error=str(exc))
            return {"outcome": Outcome.LLM_ERROR.value, "error": str(exc)}

        cost = cost_micro_usd(
            config.prices, config.model, response.input_tokens, response.output_tokens
        )
        await recorder.finish_step(
            step_id,
            StepStatus.SUCCEEDED,
            output={
                "text": response.text,
                "tool_calls": [{"id": call.id, "name": call.name} for call in response.tool_calls],
                "finish": response.finish.value,
            },
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
        await recorder.record_usage(
            model=config.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_micro_usd=cost,
        )

        update: dict[str, Any] = {
            "messages": [*state["messages"], assistant_message(response)],
            "iterations": state["iterations"] + 1,
            "input_tokens": state["input_tokens"] + response.input_tokens,
            "output_tokens": state["output_tokens"] + response.output_tokens,
            "cost_micro_usd": state["cost_micro_usd"] + cost,
            "final_text": response.text,
            "pending_tool_calls": [],
            "collected_results": [],
        }
        if response.finish is FinishReason.MAX_TOKENS:
            update["outcome"] = Outcome.TRUNCATED.value
        elif response.finish is FinishReason.REFUSED:
            update["outcome"] = Outcome.REFUSED.value
        elif response.tool_calls:
            update["pending_tool_calls"] = [
                {"id": c.id, "name": c.name, "args": c.args} for c in response.tool_calls
            ]
        elif not response.text.strip():
            update["outcome"] = Outcome.EMPTY.value
        else:
            update["outcome"] = Outcome.COMPLETED.value
        return update

    async def invoke(
        tool: ToolDefinition,
        handler: Any,
        validated: dict[str, Any],
        step: Any,
    ) -> ToolOutcome:
        """Run a validated tool call, record its result, and turn every failure into a message."""
        try:
            async with asyncio.timeout(tool.timeout_seconds):
                context = replace(deps.context, tool_config=tool.config or {})
                result = await handler(validated, context)
        except TimeoutError:
            message = f"The tool timed out after {tool.timeout_seconds} seconds."
            await recorder.finish_step(step, StepStatus.FAILED, error=message)
            return ToolOutcome(message, True)
        except ToolError as exc:
            await recorder.finish_step(step, StepStatus.FAILED, error=str(exc))
            return ToolOutcome(str(exc), True)
        except Exception:
            # Never show internals to the model or the user; the details go to the logs.
            log.exception("engine.tool_crashed", tool=tool.key)
            message = "The tool failed unexpectedly."
            await recorder.finish_step(step, StepStatus.FAILED, error=message)
            return ToolOutcome(message, True)
        await recorder.finish_step(step, StepStatus.SUCCEEDED, output=scrub(result))
        return ToolOutcome(_tool_result_text(result), False)

    async def check_arguments(
        tool: ToolDefinition, handler: Any, arguments: Any, step: Any
    ) -> tuple[dict[str, Any] | None, ToolOutcome | None]:
        """Validate and prepare arguments. Returns (arguments, None) or (None, the failure)."""
        try:
            if handler is None:
                raise ToolError("This tool is not implemented yet.")
            return prepare_arguments(
                tool.key, validate_arguments(tool.input_schema, arguments)
            ), None
        except ToolError as exc:
            await recorder.finish_step(step, StepStatus.FAILED, error=str(exc))
            return None, ToolOutcome(str(exc), True)
        except Exception:
            log.exception("engine.tool_crashed", tool=tool.key)
            message = "The tool failed unexpectedly."
            await recorder.finish_step(step, StepStatus.FAILED, error=message)
            return None, ToolOutcome(message, True)

    async def run_one_tool(call: ToolCall, reasoning: str) -> ToolOutcome | Paused:
        """Run one requested tool call, or pause it for a person's approval."""
        tool = by_llm_name.get(call.name)
        if tool is None:
            step = await recorder.start_step(StepType.TOOL_CALL, tool_key=call.name[:100])
            message = f"The tool {call.name!r} is not available to this agent."
            await recorder.finish_step(step, StepStatus.FAILED, error=message)
            return ToolOutcome(message, True)

        arguments = call.args if isinstance(call.args, dict) else {"value": call.args}
        step = await recorder.start_step(
            StepType.TOOL_CALL, name=tool.key, tool_key=tool.key, input=arguments
        )
        handler = get_handler(tool.key)
        validated, failure = await check_arguments(tool, handler, call.args, step)
        if failure is not None or validated is None:
            return failure or ToolOutcome("The tool failed unexpectedly.", True)

        if tool.needs_approval:
            approval_id = await recorder.request_approval(
                step_id=step,
                tool_key=tool.key,
                proposed_input=validated,
                reasoning_summary=reasoning,
                expires_at=datetime.now(UTC) + config.approval_ttl,
            )
            return Paused(
                {
                    "approval_id": str(approval_id),
                    "call_id": call.id,
                    "name": call.name,
                    "tool_key": tool.key,
                    "step_id": str(step),
                }
            )
        return await invoke(tool, handler, validated, step)

    async def carry_out_decision(resume: dict[str, Any]) -> ToolOutcome | None:
        """Finish the call a person decided on. None means the run was cancelled meanwhile."""
        import uuid

        awaiting = resume["awaiting"]
        step = uuid.UUID(awaiting["step_id"])
        if resume["decision"] != "approved":
            note = (resume.get("note") or "").strip()
            message = f"{REJECTED_TEXT} Their note: {note}" if note else REJECTED_TEXT
            await recorder.finish_step(step, StepStatus.SKIPPED, error=message)
            return ToolOutcome(message, True)

        if await recorder.is_cancelled():
            await recorder.finish_step(step, StepStatus.SKIPPED, error=CANCELLED_STEP)
            return None
        tool = by_llm_name.get(awaiting["name"])
        approved: dict[str, Any] = resume["arguments"]
        handler = get_handler(tool.key) if tool else None
        if tool is None or handler is None:
            message = "This tool is no longer available to this agent, so it was not run."
            await recorder.finish_step(step, StepStatus.FAILED, error=message)
            return ToolOutcome(message, True)
        # Run exactly what was approved: re-check it, and refuse if checking would change it.
        validated, failure = await check_arguments(tool, handler, approved, step)
        if failure is not None or validated is None:
            return failure or ToolOutcome(CHANGED_ACTION, True)
        if validated != approved:
            await recorder.finish_step(step, StepStatus.FAILED, error=CHANGED_ACTION)
            return ToolOutcome(CHANGED_ACTION, True)
        # Written before the action runs: if the worker dies from here on, the run reports that
        # it is unknown whether the action happened, and the action is never retried.
        if not await recorder.mark_step_running(step):
            message = "This action was no longer waiting for a decision, so it was not run."
            await recorder.finish_step(step, StepStatus.FAILED, error=message)
            return ToolOutcome(message, True)
        return await invoke(tool, handler, validated, step)

    async def run_tools(state: EngineState) -> dict[str, Any]:
        results = list(state.get("collected_results") or [])
        remaining = list(state["pending_tool_calls"])

        resume = state.get("resume")
        if resume:
            decided = await carry_out_decision(resume)
            if decided is None:
                return {"outcome": Outcome.CANCELLED.value, "resume": None}
            awaiting = resume["awaiting"]
            results.append(
                {
                    "id": awaiting["call_id"],
                    "name": awaiting["name"],
                    "content": decided.text,
                    "is_error": decided.is_error,
                }
            )

        used = state.get("tool_calls", 0)
        while remaining:
            if used >= config.limits.max_tool_calls:
                return {
                    "outcome": Outcome.TOOL_CALL_LIMIT.value,
                    "tool_calls": used,
                    "resume": None,
                }
            raw = remaining.pop(0)
            used += 1
            call = ToolCall(id=raw["id"], name=raw["name"], args=raw["args"])
            outcome = await run_one_tool(call, state.get("final_text", ""))
            if isinstance(outcome, Paused):
                return {
                    "outcome": Outcome.AWAITING_APPROVAL.value,
                    "awaiting": outcome.awaiting,
                    "collected_results": results,
                    "pending_tool_calls": remaining,
                    "tool_calls": used,
                    "resume": None,
                }
            results.append(
                {
                    "id": call.id,
                    "name": call.name,
                    "content": outcome.text,
                    "is_error": outcome.is_error,
                }
            )
        return {
            "messages": [*state["messages"], tool_message(results)],
            "tool_calls": used,
            "pending_tool_calls": [],
            "collected_results": [],
            "awaiting": {},
            "resume": None,
        }

    def at_start(state: EngineState) -> str:
        return "run_tools" if state.get("resume") else "call_model"

    def after_model(state: EngineState) -> str:
        if state.get("outcome"):
            return END
        return "run_tools" if state.get("pending_tool_calls") else END

    def after_tools(state: EngineState) -> str:
        return END if state.get("outcome") else "call_model"

    graph = StateGraph(EngineState)
    graph.add_node("call_model", call_model)
    graph.add_node("run_tools", run_tools)
    graph.add_conditional_edges(
        START, at_start, {"run_tools": "run_tools", "call_model": "call_model"}
    )
    graph.add_conditional_edges("call_model", after_model, {"run_tools": "run_tools", END: END})
    graph.add_conditional_edges("run_tools", after_tools, {"call_model": "call_model", END: END})
    return graph.compile()
