"""Тесты MCP: загрузка конфига, схемы инструментов, вызов инструментов.

Настоящие MCP-серверы не запускаются (это потребовало бы npx/node и сети):
проверяется разбор конфига, подстановки и работа с уже подключённой сессией.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from mcp_integration import MCPServer, MCPManager, load_mcp_servers


# ---------- Загрузка конфига ----------

def _write_config(project, data) -> str:
    path = project / "mcp_config.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_load_servers_with_substitutions(project, monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "секрет")
    path = _write_config(project, {"mcpServers": {
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem",
                     "${project_root}", "${env:MCP_TOKEN}"],
        },
    }})

    servers = asyncio.run(load_mcp_servers(path, {"project_root": str(project)}))

    assert len(servers) == 1
    assert servers[0].name == "filesystem"
    assert servers[0].command == "npx"
    assert servers[0].args[2] == str(project)
    assert servers[0].args[3] == "секрет"
    assert servers[0].enabled is True


def test_load_servers_skips_comments_disabled_and_broken(project, capsys):
    path = _write_config(project, {
        "_readme": "пояснение, а не сервер",
        "mcpServers": {
            "off": {"command": "npx", "enabled": False},
            "no-command": {"args": ["x"]},
            "not-an-object": "строка",
            "ok": {"command": "python", "args": ["-m", "server"]},
        },
    })

    servers = asyncio.run(load_mcp_servers(path))
    names = [srv.name for srv in servers]
    out = capsys.readouterr().out

    assert names == ["off", "ok"]
    assert servers[0].enabled is False
    assert "пропущен no-command" in out
    assert "пропущен not-an-object" in out


def test_load_servers_supports_servers_key_alias(project):
    path = _write_config(project, {"servers": {"x": {"command": "node"}}})

    servers = asyncio.run(load_mcp_servers(path))

    assert [srv.name for srv in servers] == ["x"]


def test_unresolved_substitution_becomes_empty(project):
    """Неизвестная подстановка молча превращается в пустую строку.

    Предупреждение «не раскрыта подстановка» в load_mcp_servers недостижимо:
    к моменту проверки ${...} уже заменено на пустую строку (см. отчёт о тестах).
    """
    path = _write_config(project, {"mcpServers": {
        "x": {"command": "npx", "args": ["${unknown_var}"]},
    }})

    servers = asyncio.run(load_mcp_servers(path, {"project_root": str(project)}))

    assert servers[0].args == [""]


# ---------- Схемы инструментов ----------

def test_extract_schema_from_dict():
    tool = SimpleNamespace(input_schema={"type": "object",
                                         "properties": {"path": {"type": "string"}}})

    assert MCPManager._extract_schema(tool)["properties"]["path"]["type"] == "string"


def test_extract_schema_from_pydantic_like_object():
    class Schema:
        def model_dump(self):
            return {"type": "object", "properties": {"q": {"type": "string"}}}

    assert MCPManager._extract_schema(SimpleNamespace(inputSchema=Schema())) == \
        {"type": "object", "properties": {"q": {"type": "string"}}}


def test_extract_schema_defaults_to_empty_object():
    assert MCPManager._extract_schema(SimpleNamespace()) == {
        "type": "object", "properties": {}}


# ---------- Вызов инструментов ----------

class _FakeSession:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls: list = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self._error:
            raise self._error
        return self._result


def _manager_with_tool(session) -> MCPManager:
    manager = MCPManager()
    manager._sessions["filesystem"] = session
    manager._tool_map["filesystem__read_file"] = {"server": "filesystem",
                                                  "original_name": "read_file"}
    return manager


def test_call_tool_strips_server_prefix():
    session = _FakeSession(result=SimpleNamespace(
        content=[SimpleNamespace(type="text", text="данные файла")]))
    manager = _manager_with_tool(session)

    assert asyncio.run(manager.call_tool("filesystem__read_file",
                                         {"path": "a.txt"})) == "данные файла"
    assert session.calls == [("read_file", {"path": "a.txt"})]


def test_call_tool_reports_unknown_tool_and_errors():
    manager = _manager_with_tool(_FakeSession(error=RuntimeError("сервер упал")))

    assert asyncio.run(manager.call_tool("nope", {})).startswith("ERROR: MCP-инструмент")
    assert asyncio.run(manager.call_tool("filesystem__read_file", {})).startswith(
        "ERROR при вызове")


def test_call_tool_without_session():
    manager = MCPManager()
    manager._tool_map["x__t"] = {"server": "x", "original_name": "t"}

    assert "сессия сервера x недоступна" in asyncio.run(manager.call_tool("x__t", {}))


def test_stringify_result_handles_mixed_content():
    result = SimpleNamespace(content=[
        SimpleNamespace(type="text", text="первая"),
        SimpleNamespace(type="image", data="..."),
    ])

    text = MCPManager._stringify_result(result)

    assert text.startswith("первая")
    assert "image" in text
    assert MCPManager._stringify_result(SimpleNamespace(content=[])) == "(пустой результат)"


def test_has_tool_and_server_names():
    manager = _manager_with_tool(_FakeSession())
    manager._tools.append({"type": "function", "function": {"name": "filesystem__read_file"}})

    assert manager.has_tool("filesystem__read_file") is True
    assert manager.has_tool("filesystem__write_file") is False
    assert manager.server_names() == ["filesystem"]
    assert manager.get_tools()[0]["function"]["name"] == "filesystem__read_file"


def test_disabled_server_is_not_started(capsys):
    manager = MCPManager()

    asyncio.run(manager.connect([MCPServer(name="off", command="npx", enabled=False)]))
    asyncio.run(manager.close())

    assert "пропущен (enabled=false)" in capsys.readouterr().out
    assert manager.get_tools() == []


def test_start_command_is_reported(capsys):
    """Сервер без enabled=false пытается запуститься и не роняет менеджер."""
    manager = MCPManager()

    asyncio.run(manager.connect([MCPServer(name="x", command="no-such-binary-xyz")]))

    assert "не удалось подключить x" in capsys.readouterr().out
    assert manager.get_tools() == []
    asyncio.run(manager.close())
