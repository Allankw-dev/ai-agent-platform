from app.core.config import get_settings
from app.workers.celery_app import celery_app
from app.workers.tasks import ping


def test_ping_task_returns_pong() -> None:
    assert ping() == "pong"


def test_the_scheduler_looks_for_lost_runs_on_a_schedule() -> None:
    entry = celery_app.conf.beat_schedule["recover-stale-runs"]
    assert entry["task"] == "agents.recover_stale_runs"
    assert entry["schedule"] == float(get_settings().run_recovery_interval_seconds)
    assert "agents.recover_stale_runs" in celery_app.tasks  # and the task really exists


def test_the_recovery_settings_have_sensible_defaults() -> None:
    settings = get_settings()
    assert settings.run_heartbeat_seconds == 15
    assert settings.run_stale_seconds == 60
    assert settings.run_recovery_interval_seconds == 30
    assert settings.run_max_attempts == 3
    # A run must never look dead merely because one beat was late.
    assert settings.run_stale_seconds >= 3 * settings.run_heartbeat_seconds
