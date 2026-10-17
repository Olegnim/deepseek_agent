"""Плагины агента: дополнительные инструменты из папок `paths.plugins_dirs`.

Плагин — обычный файл `.py` в папке `plugins/` проекта или самого агента
(папки ищутся по цепочке «проект → папка агента», см. `config.plugins_candidates`).
Файлы, начинающиеся с `_`, пропускаются. В плагине должна быть функция
`register(api)`:

    # plugins/hello.py
    def register(api):
        def hello(**args):
            return f"Привет, {args.get('name') or 'мир'}!"

        api.add_tool(
            name="hello",
            description="Поздороваться с пользователем",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
            func=hello,
        )

Что доступно плагину:

- `api.add_tool(...)` — добавить инструмент, который увидит модель; обработчик
  вызывается как `func(**args)`, результат приводится к строке;
- `api.project_root` / `api.settings` — корень проекта и действующие настройки;
- `api.find_resource("schema.json")` — файл из проекта или папки агента.

Инструмент с `dangerous=True` спрашивает подтверждение (как `write_file`) и
блокируется в режиме планирования; `path` в аргументах проходит ту же песочницу
(`safe_path`), что и у встроенных инструментов.

Плагин выполняется в процессе агента с его правами: подключайте только
доверенные папки. Ошибка в плагине не роняет агента — она попадает в результат
загрузки, печатается при старте и видна в `--doctor`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import config

# Имя инструмента: так же, как у встроенных (буквы, цифры, _ и -).
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class PluginAPI:
    """То, что плагин получает в `register(api)`."""

    def __init__(self, name: str, path: Path) -> None:
        self.name = name
        self.path = path
        self.tools: list[dict] = []
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.dangerous: set[str] = set()

    # ---- доступ к агенту ----

    @property
    def project_root(self) -> Path:
        """Корень проекта (песочница инструментов)."""
        return Path(config.PROJECT_ROOT)

    @property
    def settings(self) -> dict:
        """Действующие настройки (слои agent.config.json + проектного конфига)."""
        return config.SETTINGS

    def find_resource(self, relative: str) -> Path | None:
        """Файл/папка из проекта или из папки агента (что найдётся первым)."""
        return config.find_resource(relative, config.PROJECT_ROOT)

    # ---- регистрация инструментов ----

    def add_tool(self, name: str, func: Callable[..., Any], description: str = "",
                 parameters: dict | None = None, dangerous: bool = False) -> None:
        """Добавляет инструмент. Ошибки в аргументах — исключение (плагин пропущен)."""
        tool_name = str(name or "").strip()
        if not _TOOL_NAME_RE.match(tool_name):
            raise ValueError(f"недопустимое имя инструмента: {name!r}")
        if not callable(func):
            raise TypeError(f"add_tool({tool_name}): func должен быть вызываемым")
        if tool_name in self.handlers:
            raise ValueError(f"инструмент «{tool_name}» уже добавлен этим плагином")

        self.handlers[tool_name] = func
        self.tools.append({
            "type": "function",
            "function": {
                "name": tool_name,
                "description": str(description or tool_name),
                "parameters": parameters or {"type": "object", "properties": {}},
            },
        })
        if dangerous:
            self.dangerous.add(tool_name)


@dataclass
class PluginLoadResult:
    """Итог загрузки: что подключилось, что нет и почему."""

    dirs: list[Path] = field(default_factory=list)
    loaded: list[str] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    handlers: dict[str, Callable[..., Any]] = field(default_factory=dict)
    dangerous: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Одна строка для баннера при старте и `--doctor`."""
        if not self.loaded and not self.errors:
            return "нет (папки plugins/ не найдены)"
        parts = [f"{len(self.loaded)}: {', '.join(self.loaded)}" if self.loaded else "0"]
        parts.append(f"инструментов: {len(self.handlers)}")
        if self.errors:
            parts.append(f"ошибок: {len(self.errors)}")
        return ", ".join(parts)


def _plugin_files(directory: Path) -> list[Path]:
    """Файлы плагинов: только *.py, без служебных (_, .) — порядок стабильный."""
    return sorted(
        p for p in directory.glob("*.py")
        if p.is_file() and not p.name.startswith(("_", "."))
    )


def _module_name(path: Path) -> str:
    """Уникальное имя модуля: одинаковые имена файлов в разных папках не смешиваются."""
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"deepseek_plugin_{path.stem}_{digest}"


def _import_plugin(path: Path):
    """Импортирует файл плагина (повторно — свежий код, без кэша в sys.modules)."""
    name = _module_name(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"не удалось загрузить {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(name, None)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def load_plugins(directories: list[Path] | None = None,
                 reserved: set[str] | None = None) -> PluginLoadResult:
    """Загружает плагины из папок (по умолчанию — `config.plugins_candidates()`).

    directories — явный список папок (тесты, будущий `:plugins`).
    reserved — имена, занятые встроенными и MCP-инструментами: плагин не может
    их перекрыть, такой инструмент пропускается с сообщением об ошибке.
    """
    result = PluginLoadResult()
    reserved_names = set(reserved or ())

    dirs = list(directories) if directories is not None else config.plugins_candidates()
    result.dirs = [Path(d) for d in dirs]

    for directory in result.dirs:
        if not directory.is_dir():
            continue
        for path in _plugin_files(directory):
            name = path.stem
            try:
                module = _import_plugin(path)
                register = getattr(module, "register", None)
                if not callable(register):
                    result.errors.append(f"{path}: нет функции register(api) — пропущен")
                    continue

                api = PluginAPI(name=name, path=path)
                register(api)
            except Exception as e:  # noqa: BLE001 — плагин не должен ронять агента
                result.errors.append(f"{path}: {type(e).__name__}: {e}")
                continue

            added = 0
            for tool_name, func in api.handlers.items():
                if tool_name in reserved_names:
                    result.errors.append(
                        f"{path}: инструмент «{tool_name}» уже есть у агента — пропущен")
                    continue
                if tool_name in result.handlers:
                    result.errors.append(
                        f"{path}: инструмент «{tool_name}» уже добавлен другим "
                        "плагином — пропущен")
                    continue
                result.handlers[tool_name] = func
                if tool_name in api.dangerous:
                    result.dangerous.add(tool_name)
                added += 1

            result.tools.extend(
                tool for tool in api.tools
                if tool["function"]["name"] in result.handlers
            )
            result.loaded.append(name)
            if not added:
                result.errors.append(f"{path}: не добавлено ни одного инструмента")

    return result
