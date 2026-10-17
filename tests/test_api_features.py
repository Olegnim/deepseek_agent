"""Тесты возможностей DeepSeek API: thinking mode, лимиты ответа, vision.

Проверяется «проводка» настроек в запрос (`agent._request_kwargs`), разбор
ответа и передача изображений (`tools/vision.py`, `agent._run_loop`).
Сеть не используется: клиент и модель подменяются заглушками.
"""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import config
from tools import vision

# 1x1 PNG — минимальное корректное изображение.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg=="
)


class FakeClient:
    """Клиент-заглушка: запоминает kwargs запроса."""

    def __init__(self):
        self.kwargs = None
        outer = self

        class Completions:
            def create(self, **kwargs):
                outer.kwargs = kwargs
                if kwargs.get("stream"):         # стриминг: пустой поток чанков
                    return iter(())
                return SimpleNamespace(choices=[], usage=None)

        self.chat = SimpleNamespace(completions=Completions())


def _request(agent_module, monkeypatch) -> dict:
    fake = FakeClient()
    monkeypatch.setattr(agent_module, "client", fake)
    agent_module._api_request([{"role": "user", "content": "привет"}], [])
    return fake.kwargs


# ---------- Thinking mode ----------

def test_thinking_enabled_with_effort(agent_module, apply_config, monkeypatch):
    apply_config({"api": {"thinking": True, "reasoning_effort": "max"}})

    kwargs = _request(agent_module, monkeypatch)

    assert kwargs["extra_body"]["thinking"] == {"type": "enabled"}
    assert kwargs["extra_body"]["reasoning_effort"] == "max"


def test_thinking_disabled(agent_module, apply_config, monkeypatch):
    apply_config({"api": {"thinking": False}})

    kwargs = _request(agent_module, monkeypatch)

    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in kwargs["extra_body"]


def test_reasoning_effort_none_disables_thinking(agent_module, apply_config,
                                                monkeypatch):
    apply_config({"api": {"thinking": True, "reasoning_effort": "none"}})

    kwargs = _request(agent_module, monkeypatch)

    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}


def test_effort_aliases_follow_api_docs():
    assert config.normalize_reasoning_effort("minimal") == "low"
    assert config.normalize_reasoning_effort("medium") == "high"
    assert config.normalize_reasoning_effort("xhigh") == "high"
    assert config.normalize_reasoning_effort("ultra") == "max"
    assert config.normalize_reasoning_effort("disabled") == "none"
    assert config.normalize_reasoning_effort("чепуха") == "high"


def test_think_command_switches_mode(agent_module, apply_config):
    """Команда :think меняет режим только на сессию."""
    apply_config({"api": {"thinking": True, "reasoning_effort": "high"}})
    try:
        assert agent_module.cmd_think("off") is True
        assert config.thinking_enabled() is False

        assert agent_module.cmd_think("max") is True
        assert config.thinking_enabled() is True
        assert config.reasoning_effort() == "max"
    finally:
        config.set_thinking(None)
        config.set_reasoning_effort(None)

    assert config.thinking_enabled() is True           # вернулись к конфигу
    assert config.reasoning_effort() == "high"


# ---------- Лимиты ответа ----------

def test_max_tokens_and_top_p_are_passed(agent_module, apply_config, monkeypatch):
    apply_config({"api": {"max_tokens": 32000, "top_p": 0.97}})

    kwargs = _request(agent_module, monkeypatch)

    assert kwargs["max_tokens"] == 32000
    assert kwargs["top_p"] == 0.97


def test_max_tokens_not_sent_by_default(agent_module, apply_config, monkeypatch):
    apply_config({"api": {}})

    kwargs = _request(agent_module, monkeypatch)

    assert "max_tokens" not in kwargs                 # действует значение API
    assert "top_p" not in kwargs


def test_max_tokens_is_clamped_to_api_limit(project):
    (project / ".agent.config.json").write_text(
        json.dumps({"api": {"max_tokens": 999999}}), encoding="utf-8"
    )
    config.setup(str(project))

    assert config.max_output_tokens() == 393216       # 384K — максимум API


def test_reasoning_tokens_are_counted(agent_module):
    """usage.completion_tokens_details.reasoning_tokens попадает в статистику."""
    usage = SimpleNamespace(
        prompt_tokens=10, completion_tokens=20, total_tokens=30,
        prompt_cache_hit_tokens=4, prompt_cache_miss_tokens=6,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=7),
    )
    before = dict(agent_module.TOKEN_STATS)
    try:
        agent_module._update_stats(usage)
        assert agent_module.TOKEN_STATS["reasoning"] == before["reasoning"] + 7
    finally:
        agent_module.TOKEN_STATS.update(before)


# ---------- Vision ----------

def test_read_image_returns_content_parts(project):
    image = project / "shot.png"
    image.write_bytes(PNG_1X1)

    parts = vision.read_image(str(image))

    assert isinstance(parts, list) and len(parts) == 2
    assert parts[0]["type"] == "text"
    assert "shot.png" in parts[0]["text"]
    assert parts[1]["type"] == "image_url"
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


def test_read_image_detail_is_passed(project):
    image = project / "ui.png"
    image.write_bytes(PNG_1X1)

    parts = vision.read_image(str(image), detail="low")

    assert parts[1]["image_url"]["detail"] == "low"


def test_read_image_rejects_text_file(project):
    text = project / "note.png"                 # формат определяется по содержимому
    text.write_text("не картинка", encoding="utf-8")

    result = vision.read_image(str(text))

    assert isinstance(result, str) and result.startswith("ERROR")


def test_read_image_respects_size_limit(project):
    (project / ".agent.config.json").write_text(
        json.dumps({"vision": {"max_bytes": 10}}), encoding="utf-8"
    )
    config.setup(str(project))
    image = project / "big.png"
    image.write_bytes(PNG_1X1)

    result = vision.read_image(str(image))

    assert isinstance(result, str) and "лимита" in result


def test_read_file_points_to_read_image(project):
    from tools import filesystem

    (project / "screen.png").write_bytes(PNG_1X1)

    result = filesystem.read_file(str(project / "screen.png"))

    assert "read_image" in result


class FakeToolCall:
    def __init__(self, name: str, args: dict, call_id: str = "call_1"):
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=json.dumps(args))


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = None


def _install_model(agent_module, monkeypatch, script, counter):
    async def fake_call(messages, tools):
        counter["calls"] += 1
        message = script[min(counter["calls"] - 1, len(script) - 1)]
        return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                               usage=None)

    monkeypatch.setattr(agent_module, "_call_model", fake_call)


def test_image_from_tool_goes_to_user_message(agent_module, project, monkeypatch):
    """Картинка уходит отдельным user-сообщением (в system/assistant — 400)."""
    (project / "shot.png").write_bytes(PNG_1X1)
    calls = {"calls": 0}
    _install_model(agent_module, monkeypatch, [
        FakeMessage(tool_calls=[FakeToolCall("read_image", {"path": "shot.png"})]),
        FakeMessage(content="Вижу скриншот."),
    ], calls)
    messages = [{"role": "user", "content": "посмотри shot.png"}]

    asyncio.run(agent_module._run_loop(messages))

    tool_msg = next(m for m in messages if isinstance(m, dict) and m["role"] == "tool")
    assert isinstance(tool_msg["content"], str)        # текст, а не блоки
    image_msg = next(
        m for m in messages
        if isinstance(m, dict) and m["role"] == "user"
        and isinstance(m["content"], list)
    )
    assert any(p["type"] == "image_url" for p in image_msg["content"])


def test_finish_reason_length_is_reported(agent_module, project, monkeypatch, capsys):
    """finish_reason=length — видимая подсказка про api.max_tokens."""
    calls = {"calls": 0}

    async def fake_call(messages, tools):
        calls["calls"] += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=FakeMessage(content="обрезано"),
                                     finish_reason="length")],
            usage=None,
        )

    monkeypatch.setattr(agent_module, "_call_model", fake_call)
    messages = [{"role": "user", "content": "задача"}]

    asyncio.run(agent_module._run_loop(messages))

    assert "max_tokens" in capsys.readouterr().out


def test_vision_tool_hidden_when_disabled(agent_module, apply_config):
    apply_config({"vision": {"enabled": False}})

    names = {(t.get("function") or {}).get("name")
             for t in agent_module.build_tools_list()}

    assert "read_image" not in names


# ---------- Стриминг ----------

def _delta(content=None, reasoning=None, tool_calls=None):
    return SimpleNamespace(content=content, reasoning_content=reasoning,
                           tool_calls=tool_calls)


def _tool_delta(index, call_id=None, name=None, arguments=None):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=call_id, function=function)


def _chunk(delta=None, finish=None):
    choice = SimpleNamespace(delta=delta, finish_reason=finish)
    return SimpleNamespace(choices=[choice], usage=None)


def _usage_chunk(usage):
    return SimpleNamespace(choices=[], usage=usage)


def _stream_client(chunks):
    """Клиент-заглушка, отдающий заранее заготовленные чанки."""

    class FakeStreamClient:
        def __init__(self):
            self.kwargs = None
            outer = self

            class Completions:
                def create(self, **kwargs):
                    outer.kwargs = kwargs
                    return iter(chunks)

            self.chat = SimpleNamespace(completions=Completions())

    return FakeStreamClient()


def test_stream_request_collects_content(agent_module, apply_config, monkeypatch,
                                         capsys):
    apply_config({"api": {"stream": True}})
    usage = SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7)
    fake = _stream_client([
        _chunk(_delta(reasoning="думаю")),
        _chunk(_delta(content="При")),
        _chunk(_delta(content="вет"), finish="stop"),
        _usage_chunk(usage),
    ])
    monkeypatch.setattr(agent_module, "client", fake)

    response = agent_module._api_request([{"role": "user", "content": "привет"}], [])

    assert fake.kwargs["stream"] is True
    assert fake.kwargs["stream_options"] == {"include_usage": True}
    message = response.choices[0].message
    assert message.content == "Привет"
    assert message.reasoning_content == "думаю"
    assert message.tool_calls == []
    assert response.choices[0].finish_reason == "stop"
    assert response.usage is usage
    assert capsys.readouterr().out.count("Привет") == 1     # напечатан один раз


def test_stream_request_assembles_tool_calls(agent_module, apply_config, monkeypatch):
    apply_config({"api": {"stream": True}})
    fake = _stream_client([
        _chunk(_delta(tool_calls=[_tool_delta(0, "call_1", "read_file")])),
        _chunk(_delta(tool_calls=[_tool_delta(0, arguments='{"path": ')])),
        _chunk(_delta(tool_calls=[_tool_delta(0, arguments='"a.txt"}')])),
        _chunk(finish="tool_calls"),
    ])
    monkeypatch.setattr(agent_module, "client", fake)

    response = agent_module._api_request([{"role": "user", "content": "читай"}], [])

    calls = response.choices[0].message.tool_calls
    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].function.name == "read_file"
    assert json.loads(calls[0].function.arguments) == {"path": "a.txt"}


def test_streamed_message_goes_to_history_as_dict(agent_module, project,
                                                  apply_config, monkeypatch):
    """Ответ стримингом попадает в историю dict'ом (её же отправляем в API)."""
    apply_config({"api": {"stream": True}})
    (project / "a.txt").write_text("содержимое", encoding="utf-8")
    chunks = [_chunk(_delta(tool_calls=[_tool_delta(
        0, "call_1", "read_file", '{"path": "a.txt"}')]))]
    monkeypatch.setattr(agent_module, "client", _stream_client(chunks))
    messages = [{"role": "user", "content": "прочитай a.txt"}]

    asyncio.run(agent_module._run_loop(messages))

    assistant = messages[1]
    assert isinstance(assistant, dict) and assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
    assert messages[2]["role"] == "tool"


def test_stream_command_switches_mode(agent_module, apply_config):
    apply_config({"api": {"stream": True}})
    try:
        assert agent_module.cmd_stream("off") is True
        assert config.stream_enabled() is False

        assert agent_module.cmd_stream("on") is True
        assert config.stream_enabled() is True
    finally:
        config.set_stream(None)

    assert config.stream_enabled() is True          # вернулись к конфигу


def test_stream_flag_is_parsed_from_config(agent_module, apply_config):
    apply_config({"api": {"stream": False}})
    assert config.stream_enabled() is False

    apply_config({"api": {"stream": "off"}})
    assert config.stream_enabled() is False

    apply_config({"api": {"stream": "да"}})
    assert config.stream_enabled() is True
