"""Тесты защиты от зацикливания (loop_guard).

Логика крошечная, но именно она удерживает агента от бесконечного повтора
одного и того же вызова при снятом лимите шагов, поэтому сценарии проверяются
явно: предупреждение, остановка, сброс счётчика при другом результате.
"""

from __future__ import annotations

from tools import loop_guard
from tools.loop_guard import LoopGuard


def _guard(**settings):
    return LoopGuard(settings={"enabled": True, "repeat_limit": 3, **settings})


def test_disabled_guard_never_triggers():
    guard = LoopGuard(settings={"enabled": False, "repeat_limit": 3})
    assert guard.active is False
    for _ in range(10):
        assert guard.observe("read_file", {"path": "a"}, "тот же результат") is None


def test_zero_limit_disables_guard():
    assert LoopGuard(settings={"enabled": True, "repeat_limit": 0}).active is False


def test_same_call_warns_then_stops():
    guard = _guard()
    args = {"path": "src/a.php"}
    results = []

    for _ in range(3):
        results.append(guard.observe("read_file", args, "тот же результат"))
    assert results == [None, None, loop_guard.WARN]

    # После предупреждения окно начинается заново: ещё два тихих повтора —
    # и на третьем задача останавливается.
    assert guard.observe("read_file", args, "тот же результат") is None
    assert guard.observe("read_file", args, "тот же результат") is None
    assert guard.observe("read_file", args, "тот же результат") == loop_guard.STOP


def test_different_result_resets_counter():
    guard = _guard()
    args = {"path": "src/a.php"}

    guard.observe("read_file", args, "результат 1")
    guard.observe("read_file", args, "результат 2")
    guard.observe("read_file", args, "результат 3")

    # Результат меняется — это не цикл, счётчик не растёт.
    assert guard.observe("read_file", args, "результат 4") is None
    assert guard.repeat == 1


def test_different_arguments_are_not_a_cycle():
    guard = _guard()
    for i in range(5):
        assert guard.observe("read_file", {"path": f"file{i}"}, "ok") is None


def test_settings_are_taken_from_config(project):
    """Без явных настроек guard читает agent.loop_guard из конфига."""
    guard = LoopGuard()
    assert guard.active is True
    assert guard.limit == 3


def test_messages_are_human_readable():
    guard = _guard()
    args = {"path": "src/a.php"}

    warning = guard.warning("read_file", args)
    stop = guard.message("read_file", args)

    assert "read_file" in warning and "src/a.php" in warning
    assert "останавливаю задачу" in stop
    assert loop_guard.describe_call("grep", {"pattern": "TODO"}).startswith("grep {")
