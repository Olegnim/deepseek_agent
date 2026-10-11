"""Тесты ядра агента: песочница путей, реестр инструментов, системный промпт.

Модуль `agent.py` тестируется без сети и без DeepSeek API: клиент подменяется
объектом-заглушкой, который только записывает аргументы запроса.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import config


# ---------- Песочница путей ----------

def test_safe_path_inside_project(agent_module, project):
    assert agent_module.safe_path("src/file.py") == (project / "src" / "file.py")
    assert agent_module.safe_path(str(project)) == project.resolve()


@pytest.mark.parametrize("path", ["../outside.txt", "src/../../outside.txt", ".."])
def test_safe_path_blocks_paths_outside_project(agent_module, path):
    with pytest.raises(ValueError):
        agent_module.safe_path(path)


def test_safe_path_blocks_absolute_path_outside(agent_module, tmp_path):
    with pytest.raises(ValueError):
        agent_module.safe_path(str(tmp_path / "another_project" / "file.py"))


# ---------- Реестр инструментов ----------

def test_python_file_tool_executes_relative_to_project_root(agent_module, project):
    (project / "a.txt").write_text("привет", encoding="utf-8")

    result = asyncio.run(agent_module.execute_tool("read_file", {"path": "a.txt"}))

    assert result == "привет"


def test_unknown_tool_returns_error(agent_module):
    result = asyncio.run(agent_module.execute_tool("teleport", {}))

    assert result.startswith("ERROR: неизвестный инструмент")


def test_tool_path_outside_project_returns_error(agent_module):
    result = asyncio.run(agent_module.execute_tool("read_file", {"path": "../secret"}))

    assert result.startswith("ERROR: Путь вне проекта запрещён")


def test_write_file_creates_snapshot_and_runs_lint(agent_module, project, apply_config):
    apply_config({"lint": {"rules": [
        {"ext": [".py"], "command": "python -m py_compile {file}",
         "label": "python -m py_compile"},
    ]}})
    (project / "edited.py").write_text("x = 1\n", encoding="utf-8")

    result = asyncio.run(agent_module.execute_tool("write_file", {
        "path": "edited.py", "content": "x = 2\n",
    }))

    assert (project / "edited.py").read_text(encoding="utf-8") == "x = 2\n"
    assert "линт python -m py_compile: OK" in result
    # Снапшот старой версии сохранён — правку можно откатить.
    copies = list((project / ".agent-cache" / "backups").rglob("edited.py"))
    assert copies and copies[0].read_text(encoding="utf-8") == "x = 1\n"


def test_dangerous_tool_can_be_rejected(agent_module, project, monkeypatch):
    monkeypatch.setattr(agent_module, "CONFIRM_MODE", True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    result = asyncio.run(agent_module.execute_tool("write_file", {
        "path": "new.txt", "content": "не должно появиться",
    }))

    assert result.startswith("Пользователь отклонил")
    assert not (project / "new.txt").exists()


def test_confirmation_can_be_disabled_for_all(agent_module, project, monkeypatch):
    monkeypatch.setattr(agent_module, "CONFIRM_MODE", True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "a")   # a = «разрешить всё»

    first = asyncio.run(agent_module.execute_tool("write_file",
                                                  {"path": "one.txt", "content": "1"}))
    second = asyncio.run(agent_module.execute_tool("write_file",
                                                   {"path": "two.txt", "content": "2"}))

    assert "Записано" in first and "Записано" in second
    assert (project / "one.txt").exists() and (project / "two.txt").exists()


# ---------- Список инструментов для модели ----------

def _tool_names(agent_module):
    return {tool["function"]["name"] for tool in agent_module.build_tools_list()}


def test_git_tools_hidden_outside_repository(agent_module):
    assert "git_status" not in _tool_names(agent_module)

    (agent_module.PROJECT_ROOT / ".git").mkdir()

    assert "git_status" in _tool_names(agent_module)


def test_web_tools_hidden_when_disabled(agent_module, apply_config):
    apply_config({"tools": {"web": {"enabled": False}}})

    names = _tool_names(agent_module)

    assert "fetch_url" not in names and "web_search" not in names
    assert "read_file" in names        # остальные инструменты на месте


def test_vscode_tools_hidden_without_bridge(agent_module):
    assert not {name for name in _tool_names(agent_module)
                if name.startswith("vscode_")}


def test_vscode_tools_appear_with_bridge(agent_module, monkeypatch):
    monkeypatch.setattr(agent_module.vscode_tools, "available",
                        lambda force=False: True)

    assert "vscode_open" in _tool_names(agent_module)


def test_mcp_tools_do_not_override_builtin_names(agent_module, monkeypatch):
    class FakeMCP:
        def get_tools(self):
            return [{"type": "function", "function": {"name": "read_file",
                                                      "parameters": {}}}]

    monkeypatch.setattr(agent_module, "mcp_manager", FakeMCP())

    names = [tool["function"]["name"] for tool in agent_module.build_tools_list()]

    assert names.count("read_file") == 1


# ---------- Системный промпт ----------

def test_system_prompt_describes_project_stack_and_skills(agent_module, project):
    (project / "requirements.txt").write_text("", encoding="utf-8")
    skill = project / "skills" / "my-rules"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\napplies_to: [python]\n---\nПравило проекта",
                                    encoding="utf-8")

    prompt = agent_module.build_system_prompt()

    assert str(project) in prompt
    assert "Python" in prompt                 # стек определён по requirements.txt
    assert "Правило проекта" in prompt        # навык проекта попал в промпт
    assert "applies_to" not in prompt         # front-matter не показывается модели


def test_system_prompt_lists_project_autolint_rules(agent_module, apply_config):
    """В промпт попадают только правила автолинта самого проекта."""
    apply_config({"lint": {"rules": [
        {"ext": [".go"], "command": "go vet {file}", "label": "go vet"},
    ]}})

    prompt = agent_module.build_system_prompt()

    assert "go vet {file}" in prompt
    assert "php -l {file}" not in prompt       # правила других языков не подмешиваются
    assert 'run_shell("go vet путь/к/файлу")' in prompt


# ---------- Команды REPL ----------

def test_handle_command_known_and_unknown(agent_module):
    messages = [{"role": "system", "content": "s"},
                {"role": "user", "content": "u"}]

    assert asyncio.run(agent_module.handle_command(":help", messages)) is True
    assert asyncio.run(agent_module.handle_command(":clear", messages)) is True
    assert messages == []                                   # :clear очистил историю
    assert asyncio.run(agent_module.handle_command(":nope", messages)) is False


def test_profile_command_rebuilds_system_prompt(agent_module):
    messages = [{"role": "system", "content": "старый промпт"},
                {"role": "user", "content": "задача"}]

    handled = asyncio.run(agent_module.handle_command(":profile python", messages))

    assert handled is True
    assert config.agent_profile() == "python"
    assert "старый промпт" not in messages[0]["content"]
    config.set_profile(None)                                # вернуть авто-режим


# ---------- Статистика токенов ----------

def test_update_stats_accumulates_usage(agent_module):
    before = dict(agent_module.TOKEN_STATS)
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                            total_tokens=120, prompt_cache_hit_tokens=30,
                            prompt_cache_miss_tokens=70)

    agent_module._update_stats(usage)

    assert agent_module.TOKEN_STATS["prompt"] == before["prompt"] + 100
    assert agent_module.TOKEN_STATS["completion"] == before["completion"] + 20
    assert agent_module.TOKEN_STATS["cache_hit"] == before["cache_hit"] + 30
    assert agent_module.TOKEN_STATS["requests"] == before["requests"] + 1
    assert agent_module.CONTEXT_SIZE == 100
    agent_module.TOKEN_STATS.update(before)


def test_update_stats_ignores_missing_usage(agent_module):
    before = dict(agent_module.TOKEN_STATS)

    agent_module._update_stats(None)

    assert agent_module.TOKEN_STATS == before


# ---------- Регрессия: настройки API после смены проекта ----------

@pytest.mark.xfail(reason="CHANGELOG 0.1.0, «Известные проблемы»: значения api.* "
                          "из конфига целевого проекта не применяются к запросам, "
                          "если корень проекта задан флагом -p", strict=False)
def test_api_request_uses_model_from_project_config(agent_module, apply_config,
                                                    monkeypatch):
    """После config.setup() запрос должен уходить с моделью из проектного конфига."""
    apply_config({"api": {"model": "project-model-xyz", "temperature": 0.9}})

    class FakeClient:
        def __init__(self):
            self.kwargs = None
            outer = self

            class Completions:
                def create(self, **kwargs):
                    outer.kwargs = kwargs
                    return SimpleNamespace(choices=[], usage=None)

            self.chat = SimpleNamespace(completions=Completions())

    fake = FakeClient()
    monkeypatch.setattr(agent_module, "client", fake)

    agent_module._api_request([{"role": "user", "content": "привет"}], [])

    assert fake.kwargs["model"] == config.MODEL == "project-model-xyz"
    assert fake.kwargs["temperature"] == pytest.approx(0.9)


def test_request_payload_shape(agent_module, monkeypatch):
    """Запрос содержит модель, сообщения, инструменты и tool_choice."""
    calls = {}

    class FakeClient:
        chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kwargs: calls.update(kwargs) or SimpleNamespace(
                choices=[], usage=None)))

    monkeypatch.setattr(agent_module, "client", FakeClient())

    agent_module._api_request([{"role": "user", "content": "привет"}],
                              [{"type": "function",
                                "function": {"name": "read_file"}}])

    assert calls["model"] == config.MODEL
    assert calls["tool_choice"] == "auto"
    assert isinstance(calls["messages"], list)
    assert json.dumps(calls["tools"]) != ""      # список инструментов сериализуем
