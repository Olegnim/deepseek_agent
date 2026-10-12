"""
Подключение к MCP-серверам через stdio.

Совместим с MCP SDK v1 и v2 (inputSchema / input_schema).
Имена инструментов префиксуются именем сервера: filesystem__read_file.
Это устраняет конфликт с встроенными инструментами агента.
"""

import json
import os
import shutil
from collections.abc import Iterable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# Раскрытие ${env:VAR} / ${project_root} / ${agent_home} живёт в config.py,
# чтобы не дублировать одну и ту же логику в двух модулях.
from config import expand_vars as substitute


# ---------- Модель конфигурации ----------

@dataclass
class MCPServer:
    """Описание одного MCP-сервера из конфига."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    enabled: bool = True


# ---------- Запуск команды сервера (кроссплатформенно) ----------

def resolve_server_command(command: str,
                           args: Sequence[str] | None = None) -> tuple[str, list[str]]:
    """Готовит команду запуска MCP-сервера для текущей ОС.

    MCP SDK (anyio) запускает процесс напрямую, без shell, и на Windows это
    означает две проблемы: `npx` в PATH — это `npx.cmd`, который без shell
    не находится (нужен полный путь, как его отдаёт `shutil.which` с PATHEXT),
    а `.cmd`/`.bat` вообще нельзя запустить как исполняемый файл — только через
    командный интерпретатор. Поэтому такие команды оборачиваются в `cmd /c`.
    На Linux/macOS достаточно найденного в PATH пути.
    """
    text = str(command or "").strip()
    launch_args = [str(a) for a in (args or [])]
    if not text:
        return text, launch_args

    resolved = shutil.which(text) or text
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return comspec, ["/c", resolved, *launch_args]
    return resolved, launch_args


# ---------- MCP roots (разрешённые папки) ----------

def root_entries(paths: Iterable[str | Path] | None) -> list[tuple[str, str]]:
    """Превращает пути в пары (file-URI, имя папки) для протокола roots/list.

    URI собирается через Path.as_uri(), поэтому одинаково работает и на macOS
    (`file:///Users/...`), и на Windows (`file:///C:/Users/...`). Путь
    нормализуется resolve() — это важно на macOS, где /tmp и /var это симлинки
    на /private/..., и сервер сравнивает уже реальные пути.
    Несуществующие папки отбрасываются: сервер такие корни всё равно отвергнет.
    """
    entries: list[tuple[str, str]] = []
    for raw in paths or []:
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            path = path.resolve()
        except OSError:
            continue
        if not path.is_dir():
            continue
        uri = path.as_uri()
        if all(uri != existing for existing, _ in entries):
            entries.append((uri, path.name or str(path)))
    return entries


def roots_for_server(roots: Iterable[str | Path] | None,
                     args: Iterable[str] | None) -> list[str | Path]:
    """Корни для одного сервера: настройки агента + папки из его аргументов.

    Сервер мог получить разрешённые папки аргументами командной строки
    (например, `server-filesystem /path/to/project`). Когда корни начинает
    объявлять клиент, сервер заменяет ими список из аргументов — поэтому папки
    из args добавляем в набор, чтобы доступ не сузился. Флаги и обычные файлы
    пропускаются.
    """
    result: list[str | Path] = list(roots or [])
    known = {str(item) for item in result}
    for arg in args or []:
        text = str(arg).strip()
        if not text or text.startswith("-") or "://" in text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.is_dir() or str(path) in known:
            continue
        known.add(str(path))
        result.append(path)
    return result


def list_roots_handler(paths: Iterable[str | Path] | None):
    """Колбэк `roots/list` для ClientSession или None, если корней нет.

    Пока колбэк не передан, MCP SDK не объявляет серверу capability `roots`,
    и сервер (например, @modelcontextprotocol/server-filesystem) сам решает,
    какие папки разрешены: берёт их из аргументов командной строки и пишет в
    stderr «Client does not support MCP Roots, using allowed directories set
    from server args». С колбэком папки задаёт агент.
    """
    entries = root_entries(paths)
    if not entries:
        return None

    async def handler(context: Any) -> types.ListRootsResult:
        return types.ListRootsResult(
            roots=[types.Root(uri=uri, name=name) for uri, name in entries]
        )

    return handler


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

    async def connect(self, servers: list[MCPServer],
                      roots: Sequence[str | Path] | None = None) -> None:
        """Подключается ко всем серверам и собирает список инструментов.

        roots — папки из настроек агента (config.mcp_roots). Папки, переданные
        серверу аргументами командной строки, добавляются автоматически.
        Если валидных папок нет вовсе, клиент не объявляет capability `roots`,
        и сервер использует папки из своих аргументов.

        Ошибка одного сервера не прерывает подключение остальных.
        """
        for srv in servers:
            if not srv.enabled:
                print(f"[MCP] пропущен (enabled=false): {srv.name}")
                continue

            # Корни считаются для каждого сервера отдельно: его собственные
            # папки-аргументы не «протекают» в другие серверы.
            list_roots = list_roots_handler(roots_for_server(roots, srv.args))

            try:
                # Путь/обёртку команды готовим сами: на Windows `npx` — это
                # `npx.cmd`, который SDK (без shell) не найдёт.
                launch_command, launch_args = resolve_server_command(
                    srv.command, srv.args
                )
                params = StdioServerParameters(
                    command=launch_command,
                    args=launch_args,
                    env=srv.env,
                )

                read, write = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write, list_roots_callback=list_roots)
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