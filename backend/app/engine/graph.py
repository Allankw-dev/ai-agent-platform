"""The agent loop, as a LangGraph state graph.

    START -> call_model --(tool calls requested)--> run_tools -> call_model ...
                  |
                  +--(finished, or a limit/error was hit)--> END

`call_model` checks the run's limits before spending anything, then asks the model for its next
move. `run_tools` executes each requested tool after validating it, one at a time. Every model
call and tool call is recorded as a run step as it happens.

Tool arguments come from the model and are never trusted: unknown tools, tools the agent was not
granted, tools that need a person's approval, arguments that break the schema, slow handlers and
crashing handlers each end in an error result that is fed back to the model, never in an action.
"""

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

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
from app.engine.pricing import ModelPrice, cost_micro_usd
from app.engine.recorder import MAX_TEXT_CHARS, RunRecorder, scrub
from app.models.enums import StepStatus, StepType
from app.tools import get_handler
from app.tools.base import ToolContext, ToolDefinition, ToolError, validate_arguments

log = structlog.get_logger()

APPROVAL_NOT_AVAILABLE = (
    "This action needs a person's approval, and approvals are not available yet, so it was not run."
)


class Outcome(StrEnum):
    COMPLETED = "completed"
    EMPTY = "empty"
    TRUNCATED = "truncated"
    REFUSED = "refused"
    LLM_ERROR = "llm_error"
    ITERATION_LIMIT = "iteration_limit"
    TOKEN_LIMIT = "token_limit"  # noqa: S105 (an outcome label, not a secret)
    COST_LIMIT = "cost_limit"
    CANCELLED = "cancelled"


class EngineState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    iterations: int
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    final_text: str
    outcome: str  # an Outcome value once the loop has finished; empty while it is running
    error: str


@dataclass(frozen=True)
class EngineConfig:
    model: str
    system: str
    max_output_tokens: int | None
    limits: EffectiveLimits
    prices: dict[str, ModelPrice]


@dataclass(frozen=True)
class EngineDeps:
    llm: LLMClient
    recorder: RunRecorder
    tools: list[ToolDefinition]
    config: EngineConfig
    context: ToolContext


def initial_state(message: str) -> EngineState:
    return {
        "messages": [user_message(message)],
        "pending_tool_calls": [],
        "iterations": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_micro_usd": 0,
        "final_text": "",
        "outcome": "",
        "error": "",
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

    async def run_one_tool(call: ToolCall) -> tuple[str, bool]:
        """Run one requested tool call. Returns (text for the model, is_error)."""
        tool = by_llm_name.get(call.name)
        if tool is None:
            step = await recorder.start_step(StepType.TOOL_CALL, tool_key=call.name[:100])
            message = f"The tool {call.name!r} is not available to this agent."
            await recorder.finish_step(step, StepStatus.FAILED, error=message)
            return message, True

        arguments = call.args if isinstance(call.args, dict) else {"value": call.args}
        step = await recorder.start_step(
            StepType.TOOL_CALL, name=tool.key, tool_key=tool.key, input=arguments
        )

        if tool.needs_approval:
            await recorder.finish_step(step, StepStatus.SKIPPED, error=APPROVAL_NOT_AVAILABLE)
            return APPROVAL_NOT_AVAILABLE, True

        handler = get_handler(tool.key)
        try:
            if handler is None:
                raise ToolError("This tool is not implemented yet.")
            validated = validate_arguments(tool.input_schema, call.args)
            async with asyncio.timeout(tool.timeout_seconds):
                result = await handler(validated, deps.context)
        except TimeoutError:
            message = f"The tool timed out after {tool.timeout_seconds} seconds."
            await recorder.finish_step(step, StepStatus.FAILED, error=message)
            return message, True
        except ToolError as exc:
            await recorder.finish_step(step, StepStatus.FAILED, error=str(exc))
            return str(exc), True
        except Exception:
            # Never show internals to the model or the user; the details go to the logs.
            log.exception("engine.tool_crashed", tool=tool.key)
            message = "The tool failed unexpectedly."
            await recorder.finish_step(step, StepStatus.FAILED, error=message)
            return message, True

        await recorder.finish_step(step, StepStatus.SUCCEEDED, output=scrub(result))
        return _tool_result_text(result), False

    async def run_tools(state: EngineState) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for raw in state["pending_tool_calls"]:
            call = ToolCall(id=raw["id"], name=raw["name"], args=raw["args"])
            text, is_error = await run_one_tool(call)
            results.append(
                {"id": call.id, "name": call.name, "content": text, "is_error": is_error}
            )
        return {
            "messages": [*state["messages"], tool_message(results)],
            "pending_tool_calls": [],
        }

    def after_model(state: EngineState) -> str:
        if state.get("outcome"):
            return END
        return "run_tools" if state.get("pending_tool_calls") else END

    graph = StateGraph(EngineState)
    graph.add_node("call_model", call_model)
    graph.add_node("run_tools", run_tools)
    graph.add_edge(START, "call_model")
    graph.add_conditional_edges("call_model", after_model, {"run_tools": "run_tools", END: END})
    graph.add_edge("run_tools", "call_model")
    return graph.compile()
