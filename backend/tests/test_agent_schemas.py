import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentConfig, AgentCreate, AgentUpdate, ModelParams

VALID = {"model": "gemini-flash-latest", "system_instructions": "You help with support tickets."}


def test_a_minimal_configuration_gets_safe_defaults() -> None:
    config = AgentConfig.model_validate(VALID)
    assert config.provider.value == "gemini"
    assert config.limits.max_iterations == 10
    assert config.limits.timeout_seconds == 120
    assert config.limits.max_total_tokens == 50_000
    assert config.limits.cost_budget_usd is None
    assert config.memory_config.conversation_memory is True
    assert config.tools == []


@pytest.mark.parametrize(
    "override",
    [
        {"system_instructions": ""},
        {"system_instructions": "   "},
        {"model": ""},
        {"model": "has space"},
        {"model": "evil;drop"},
        {"model": "x" * 101},
        {"provider": "openai"},
        {"objectives": "x" * 4_001},
        {"unexpected": 1},
        {"model_params": {"temperature": 0.2}},  # newer models reject non-default temperature
        {"model_params": {"max_output_tokens": 0}},
        {"limits": {"max_iterations": 0}},
        {"limits": {"timeout_seconds": 1}},
        {"limits": {"max_total_tokens": 10}},
        {"limits": {"cost_budget_usd": 0}},
        {"limits": {"cost_budget_usd": -1}},
        {"limits": {"surprise": True}},
        {"memory_config": {"max_history_messages": 0}},
        {"tools": [{"tool_key": "nodots"}]},
        {"tools": [{"tool_key": "Bad.Key"}]},
        {"tools": [{"tool_key": "a.b"}, {"tool_key": "a.b"}]},
        {"tools": [{"tool_key": "a.b", "config": {"big": "x" * 11_000}}]},
        {"tools": [{"tool_key": "a.b", "unknown": 1}]},
    ],
)
def test_invalid_configurations_are_rejected(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AgentConfig.model_validate({**VALID, **override})


def test_blank_objectives_become_none_and_model_is_trimmed() -> None:
    config = AgentConfig.model_validate({**VALID, "objectives": "  ", "model": " gemini-x "})
    assert config.objectives is None
    assert config.model == "gemini-x"


def test_names_are_trimmed_and_length_checked() -> None:
    assert AgentCreate.model_validate({"name": "  Bot  ", "config": VALID}).name == "Bot"
    for bad in ["", " ", "a", " a "]:
        with pytest.raises(ValidationError):
            AgentCreate.model_validate({"name": bad, "config": VALID})


def test_updates_need_something_to_change_and_only_known_statuses() -> None:
    with pytest.raises(ValidationError):
        AgentUpdate.model_validate({})
    with pytest.raises(ValidationError):
        AgentUpdate.model_validate({"status": "archived"})
    assert AgentUpdate.model_validate({"status": "active"}).status == "active"
    assert AgentUpdate.model_validate({"description": None}).description is None


def test_model_params_have_no_temperature_field() -> None:
    assert "temperature" not in ModelParams.model_fields
