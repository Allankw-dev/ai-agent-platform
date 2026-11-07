from app.workers.tasks import ping


def test_ping_task_returns_pong() -> None:
    assert ping() == "pong"
