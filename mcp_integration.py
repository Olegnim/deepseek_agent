"""
Подключение к MCP-серверам через stdio.

Совместим с MCP SDK v1 и v2 (inputSchema / input_schema).
Имена инструментов префиксуются именем сервера: filesystem__read_file.
Это устраняет конфликт с встроенными инструментами агента.
"""

import json
import os
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ---------- Модель конфигурации ----------

@dataclass
class MCPServer:
    """Описание одного MCP-сервера из конфига."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    enabled: bool = True


# ---------- Менеджер сессий ----------

class MCPManager:
    """Держит несколько MCP-сессий и предоставляет единый интерфейс
    для агента: список инструментов в формате OpenAI/DeepSeek + вызов."""

    def __init__(self):
        self._sessions: dict[str, ClientSession] = {}
        self._exit_stack = AsyncExitStack()
        self._tools: list[dict] = []          # формат tools= для API
        # tool_name (с префиксом) -> {"server": str, "original_name": str}
        self._tool_map: dict[str, dict] = {}

    async def connect(self, servers: list[MCPServer]) -> None:
        """Подключается ко всем серверам и собирает список инструментов.

        Ошибка одного сервера не прерывает подключение остальных.
        """
        for srv in servers:
            if not srv.enabled:
                print(f"[MCP] пропущен (enabled=false): {srv.name}")
                continue

            try:
                params = StdioServerParameters(
                    command=srv.command,
                    args=srv.args,
                    env=srv.env,
                )

                read, write = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()

                self._sessions[srv.name] = session

                tools_resp = await session.list_tools()
                tools = getattr(tools_resp, "tools", []) or []

                for tool in tools:
                    schema = self._extract_schema(tool)
                    prefixed = f"{srv.name}__{tool.name}"
                    self._tools.append({
                        "type": "function",
                        "function": {
                            "name": prefixed,
                            "description": (getattr(tool, "description", "") or "")
                                           + f"  [MCP:{srv.name}]",
                            "parameters": schema,
                        },
                    })
                    self._tool_map[prefixed] = {
                        "server": srv.name,
                        "original_name": tool.name,
                    }

                print(f"[MCP] подключён: {srv.name} ({len(tools)} инструментов)")

            except Exception as e:
                print(f"[MCP] не удалось подключить {srv.name}: "
                      f"{type(e).__name__}: {e}")

    @staticmethod
    def _extract_schema(tool: Any) -> dict:
        """Достаёт input-схему. Поддерживает MCP SDK v1 и v2."""
        schema = (
            getattr(tool, "input_schema", None)
            or getattr(tool, "inputSchema", None)
        )
        if not schema:
            return {"type": "object", "properties": {}}
        if hasattr(schema, "model_dump"):
            return schema.model_dump()
        if hasattr(schema, "dict"):
            return schema.dict()
        return schema

    def get_tools(self) -> list[dict]:
        """Список инструментов в формате tools= для DeepSeek."""
        return self._tools

    def has_tool(self, name: str) -> bool:
        """Проверяет, зарегистрирован ли инструмент MCP-сервера."""
        return name in self._tool_map

    def server_names(self) -> list[str]:
        """Список имён подключённых серверов."""
        return list(self._sessions.keys())

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Вызывает инструмент на нужном сервере и возвращает текст."""
        info = self._tool_map.get(name)
        if not info:
            return f"ERROR: MCP-инструмент не найден: {name}"

        server_name = info["server"]
        original = info["original_name"]
        session = self._sessions.get(server_name)
        if session is None:
            return f"ERROR: сессия сервера {server_name} недоступна"

        try:
            result = await session.call_tool(original, arguments)
            return self._stringify_result(result)
        except Exception as e:
            return f"ERROR при вызове {name}: {type(e).__name__}: {e}"

    @staticmethod
    def _stringify_result(result: Any) -> str:
        """MCP возвращает список content-блоков.
        Достаём текстовые части, остальное — str()."""
        parts: list[str] = []
        for item in getattr(result, "content", []) or []:
            item_type = getattr(item, "type", None)
            if item_type == "text":
                parts.append(getattr(item, "text", "") or "")
            else:
                parts.append(str(item))
        return "\n".join(parts) if parts else "(пустой результат)"

    async def close(self) -> None:
        """Закрывает все сессии и дочерние процессы."""
        try:
            await self._exit_stack.aclose()
        except Exception as e:
            print(f"[MCP] ошибка при закрытии: {e}")


# ---------- Загрузка конфига ----------

_VAR_RE = re.compile(r"\$\{([^{}]+)\}")


def substitute(value: Any, variables: dict[str, str] | None = None) -> Any:
    """Раскрывает ${var} в строках/списках/словарях.

    Поддерживаются переменные из переданного словаря и ${env:VAR_NAME}.
    Так в mcp_config.json можно писать "${project_root}" вместо D:/...
    """
    variables = variables or {}

    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            key = match.group(1).strip()
            if key.startswith("env:"):
                return os.environ.get(key[4:].strip(), "")
            return str(variables.get(key, ""))

        return _VAR_RE.sub(repl, value)
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    return value


# ---------- Загрузка конфига ----------

async def load_mcp_servers(config_path: str,
                           variables: dict[str, str] | None = None) -> list[MCPServer]:
    """Читает конфиг MCP-серверов из JSON-файла.

    Формат — как у Claude Desktop / VS Code:
    {
      "mcpServers": {
        "filesystem": {
          "enabled": true,
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem",
                   "${project_root}"]
        }
      }
    }

    variables — подстановки вида ${project_root}. Сами пути и настройки
    задаются в agent.config.json, а не прямо в mcp_config.json.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    servers_cfg = data.get("mcpServers") or data.get("servers") or {}
    servers: list[MCPServer] = []

    for name, cfg in servers_cfg.items():
        if str(name).startswith("_"):        # служебные ключи-комментарии
            continue
        if not isinstance(cfg, dict):
            print(f"[MCP] пропущен {name}: ожидался объект")
            continue

        cfg = substitute(cfg, variables)

        command = cfg.get("command")
        if not command:
            print(f"[MCP] пропущен {name}: не указан command")
            continue

        args = list(cfg.get("args", []))
        for value in [command, *args]:
            if isinstance(value, str) and "${" in value:
                print(f"[MCP] {name}: не раскрыта подстановка {value} "
                      f"— проверьте agent.config.json")

        servers.append(MCPServer(
            name=name,
            command=command,
            args=args,
            env=cfg.get("env") or None,
            enabled=bool(cfg.get("enabled", True)),
        ))

    return servers