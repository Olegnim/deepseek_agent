"""Тесты цикла задачи: вызовы инструментов, обработка ошибок, зацикливание.

Модель подменяется заглушками, поэтому тесты детерминированы, быстры и не
требуют API-ключа. Проверяется именно «проводка»: какие сообщения агент
добавляет в диалог, когда останавливается и что отдаёт инструментам.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import config


class FakeToolCall:
    def __init__(self, name: str, args: dict, call_id: str = "call_1"):
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=json.dumps(args))


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = None


class FakeResponse:
    def __init__(self, message: FakeMessage, usage=None):
        self.choices = [SimpleNamespace(message=message)]
        self.usage = usage


def _install_model(agent, monkeypatch, script, counter):
    """Подменяет модель «скриптом» ответов.

    Последний ответ сценария повторяется, пока агент не остановится сам —
    так проверяются и защита от зацикливания, и лимит шагов. Если агент
    не останавливается за 20 вызовов, тест падает, а не зависает.
    """
    async def fake_call(messages, tools):
        counter["calls"] += 1
        assert counter["calls"] <= 20, "агент не остановился — цикл не пойман"
        return script[min(counter["calls"] - 1, len(script) - 1)]

    monkeypatch.setattr(agent, "_call_model", fake_call)


def test_tool_call_flow_appends_result_to_dialogue(agent_module, project, monkeypatch):
    (project / "a.txt").write_text("содержимое файла", encoding="utf-8")
    calls = {"calls": 0}
    _install_model(agent_module, monkeypatch, [
        FakeResponse(FakeMessage(tool_calls=[FakeToolCall("read_file",
                                                          {"path": "a.txt"})])),
        FakeResponse(FakeMessage(content="Готово.")),
    ], calls)
    messages = [{"role": "user", "content": "прочитай a.txt"}]

    asyncio.run(agent_module._run_loop(messages))

    assert calls["calls"] == 2                    # вызов инструмента + финальный ответ
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_1"
    assert "содержимое файла" in messages[2]["content"]


def test_execution_error_is_returned_to_model_without_crash(agent_module, monkeypatch):
    calls = {"calls": 0}
    _install_model(agent_module, monkeypatch, [
        FakeResponse(FakeMessage(tool_calls=[FakeToolCall("read_file",
                                                          {"path": "нет.txt"})])),
        FakeResponse(FakeMessage(content="Файла нет — сообщаю пользователю.")),
    ], calls)
    messages = [{"role": "user", "content": "прочитай нет.txt"}]

    asyncio.run(agent_module._run_loop(messages))

    assert messages[2]["content"].startswith("ERROR")


def test_broken_tool_arguments_do_not_crash(agent_module, monkeypatch):
    calls = {"calls": 0}
    broken = FakeMessage(tool_calls=[FakeToolCall("read_file", {})])
    broken.tool_calls[0].function.arguments = "{ это не json"
    _install_model(agent_module, monkeypatch, [
        FakeResponse(broken),
        FakeResponse(FakeMessage(content="ок")),
    ], calls)
    messages = [{"role": "user", "content": "прочитай что-нибудь"}]

    asyncio.run(agent_module._run_loop(messages))

    assert messages[2]["role"] == "tool"          # диалог не разорван


def test_repeated_identical_calls_stop_the_task(agent_module, project, monkeypatch):
    """Один и тот же вызов с тем же результатом: предупреждение, затем остановка."""
    (project / "a.txt").write_text("одно и то же", encoding="utf-8")
    calls = {"calls": 0}
    _install_model(agent_module, monkeypatch, [
        FakeResponse(FakeMessage(tool_calls=[FakeToolCall("read_file",
                                                          {"path": "a.txt"})])),
    ], calls)
    messages = [{"role": "user", "content": "читай одно и то же"}]

    asyncio.run(agent_module._run_loop(messages))

    # 3 повтора до предупреждения + 3 до остановки (agent.loop_guard.repeat_limit).
    assert calls["calls"] == 6
    assert any(isinstance(m, dict) and str(m.get("content", "")).startswith("[loop-guard]")
               for m in messages)


def test_max_steps_limit_stops_the_task(agent_module, monkeypatch):
    monkeypatch.setattr(config, "MAX_STEPS", 2)
    calls = {"calls": 0}
    _install_model(agent_module, monkeypatch, [
        FakeResponse(FakeMessage(tool_calls=[FakeToolCall("list_dir", {"path": "."})])),
    ], calls)

    asyncio.run(agent_module._run_loop([{"role": "user", "content": "перечисляй"}]))

    assert calls["calls"] == 2


def test_api_failure_ends_the_task_quietly(agent_module, monkeypatch):
    calls = {"calls": 0}

    async def failing_call(messages, tools):
        calls["calls"] += 1
        return None                        # _call_model вернула None после ретраев

    monkeypatch.setattr(agent_module, "_call_model", failing_call)

    asyncio.run(agent_module._run_loop([{"role": "user", "content": "привет"}]))

    assert calls["calls"] == 1


def test_retryable_errors_are_detected():
    from agent import _is_retryable

    class RateLimit(Exception):
        status_code = 429

    class ServerError(Exception):
        status_code = 503

    class BadRequest(Exception):
        status_code = 400

    assert _is_retryable(RateLimit()) is True
    assert _is_retryable(ServerError()) is True
    assert _is_retryable(BadRequest()) is False
    assert _is_retryable(TimeoutError()) is False


def test_session_stats_before_and_after_requests(agent_module):
    saved = dict(agent_module.TOKEN_STATS)
    try:
        agent_module.TOKEN_STATS.update(prompt=0, completion=0, total=0,
                                        cache_hit=0, cache_miss=0, requests=0)
        assert agent_module._session_stats() == "токенов пока не потрачено"

        agent_module.TOKEN_STATS.update(prompt=10, completion=2, total=12, requests=1)
        assert "1 зап." in agent_module._session_stats()
    finally:
        agent_module.TOKEN_STATS.update(saved)
