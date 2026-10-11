"""Центральная конфигурация DeepSeek CLI Agent.

Два независимых понятия:

1. AGENT_HOME — папка, где лежит сам агент (agent.py, tools/, skills/, плагины).
   Определяется АВТОМАТИЧЕСКИ из расположения этого файла, задавать не нужно.
   Переопределяется переменной окружения DEEPSEEK_AGENT_HOME (нужна, только если
   agent.py стоит в site-packages или запускается из ярлыка).

2. PROJECT_ROOT — папка проекта, с которым работает агент (песочница: за её
   пределы инструменты не выйдут). По умолчанию — папка запуска (cwd), то есть
   корень, открытый в терминале VS Code. Задавать её в конфиге не обязательно.

Все настройки живут в редактируемых JSON-файлах:

    <AGENT_HOME>/agent.config.json          — базовые настройки агента
    <PROJECT_ROOT>/.agent.config.json       — необязательный оверрайд для проекта
                                              (подхватывается автоматически)

Приоритет project_root:
    флаг -p  >  DEEPSEEK_PROJECT_ROOT  >  .agent.config.json в cwd  >
    agent.config.json  >  cwd

Приоритет остальных настроек:
    проектный конфиг  >  agent.config.json  >  DEFAULTS

Поиск общих ресурсов (навыки, MCP-конфиги, плагины) идёт автоматически по
цепочке: сначала в проекте, затем в AGENT_HOME.

Подстановки внутри строк JSON:
    ${env:VAR_NAME}   — значение переменной окружения (пусто, если нет)
    ${agent_home}     — папка агента (синоним: ${agent_dir})
    ${project_root}   — корень проекта
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# ---------- Папка агента: определяется автоматически ----------

AGENT_HOME = Path(
    os.environ.get("DEEPSEEK_AGENT_HOME") or Path(__file__).resolve().parent
).expanduser().resolve()

# Синоним для обратной совместимости.
AGENT_DIR = AGENT_HOME

CONFIG_NAME = "agent.config.json"
CONFIG_PATH = AGENT_HOME / CONFIG_NAME

# Конфиг с таким именем в корне проекта перекрывает агентский.
PROJECT_CONFIG_NAMES = (".agent.config.json", "agent.config.json")

# Значения по умолчанию: используются, если файла нет или ключ не задан.
DEFAULTS: dict = {
    "api": {
        "api_key": "",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "temperature": 0.2,
        "context_limit": 65536,
    },
    "paths": {
        # Пусто = папка запуска (cwd). Переопределяется -p / DEEPSEEK_PROJECT_ROOT.
        "project_root": "",
        # Папка навыков (SKILL.md). Относительный путь ищется в проекте,
        # затем в AGENT_HOME.
        "skills_dir": "skills",
        # Конфиг(и) MCP-серверов: строка или список строк. Относительный путь
        # ищется и в проекте, и в AGENT_HOME — найденные конфиги объединяются
        # (серверы проекта имеют приоритет по имени).
        "mcp_config": ["mcp_config.json", ".mcp.json"],
        # Каталог автоснапшотов. Относительный путь считается от проекта.
        "backup_dir": ".agent-cache/backups",
        # Дополнительные папки модулей/плагинов агента (можно указать список).
        "plugins_dirs": ["plugins"],
    },
    "snapshots": {
        "max_backups": 50,
    },
    "agent": {
        # Максимум шагов модели (запросов к API) на одну задачу.
        # Защита от зацикливания, когда модель повторяет один и тот же вызов.
        "max_steps": 25,
        # Сколько раз повторять запрос к API при сетевой ошибке/429.
        "api_retries": 3,
    },
    "tools": {
        # Таймаут shell-команд, секунды.
        "shell_timeout": 60,
        # Встроенный доступ в интернет (tools/web.py): fetch_url + web_search.
        "web": {
            "enabled": True,
            "timeout": 20,        # таймаут одного HTTP-запроса, сек
            "max_chars": 20000,   # сколько символов страницы отдавать модели
            "results": 5,         # сколько результатов поиска возвращать
        },
    },
}

_VAR_RE = re.compile(r"\$\{([^{}]+)\}")

# Какие конфиги реально прочитаны при последнем setup() — для :config и :doctor.
LOADED_CONFIGS: list[Path] = []


# ---------- Базовые помощники ----------

def deep_merge(base: dict, extra: dict) -> dict:
    """Рекурсивно накладывает extra на base. base не мутируется."""
    result = dict(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def expand_vars(value, variables: dict) -> object:
    """Раскрывает ${env:VAR}, ${agent_home}, ${project_root} в строках/списках/dict."""
    variables = variables or {}
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            key = match.group(1).strip()
            if key.startswith("env:"):
                return os.environ.get(key[4:].strip(), "")
            if key == "agent_dir":
                key = "agent_home"
            return str(variables.get(key, ""))

        return _VAR_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: expand_vars(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_vars(v, variables) for v in value]
    return value


def _read_json(path: Path) -> dict:
    """Читает JSON-файл. Битый/отсутствующий файл не роняет агента."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[config] {path}: {type(e).__name__}: {e} — файл пропущен")
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_path(value: str, base: Path) -> Path:
    """Раскрывает ~, достраивает относительный путь от base, нормализует."""
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _as_list(value) -> list[str]:
    """Приводит строку/список к списку непустых строк."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v) for v in value if str(v).strip()]


# ---------- Определение корня проекта ----------

def resolve_project_root(cli_root: str | None = None) -> Path:
    """Вычисляет корень проекта по приоритету:

        -p  >  DEEPSEEK_PROJECT_ROOT  >  конфиг в cwd  >  конфиг агента  >  cwd
    """
    if cli_root:
        return _normalize_path(cli_root, Path.cwd())

    env_root = (os.environ.get("DEEPSEEK_PROJECT_ROOT") or "").strip()
    if env_root:
        return _normalize_path(env_root, Path.cwd())

    # Конфиг, лежащий в папке запуска (типичный случай: VS Code открыт на проекте).
    for name in PROJECT_CONFIG_NAMES:
        cfg = Path.cwd() / name
        value = ((_read_json(cfg).get("paths") or {}).get("project_root") or "")
        if str(value).strip():
            return _normalize_path(str(value), cfg.parent)

    # Конфиг агента.
    value = ((_read_json(CONFIG_PATH).get("paths") or {}).get("project_root") or "")
    if str(value).strip():
        return _normalize_path(str(value), AGENT_HOME)

    return Path.cwd().resolve()


# ---------- Загрузка настроек ----------

def setup(cli_project_root: str | None = None) -> Path:
    """Определяет PROJECT_ROOT, читает конфиги и обновляет константы модуля.

    Вызывается автоматически при импорте и повторно из agent.main() (когда
    передан флаг -p или нужен свежий расчёт после смены cwd).
    """
    global SETTINGS, API, PATHS, SNAPSHOTS, AGENT_CFG, TOOLS_CFG, WEB
    global PROJECT_ROOT, LOADED_CONFIGS
    global API_KEY, BASE_URL, MODEL, TEMPERATURE, CONTEXT_LIMIT, MAX_BACKUPS
    global MAX_STEPS, API_RETRIES, SHELL_TIMEOUT

    root = resolve_project_root(cli_project_root)

    # Агентский конфиг + (если есть) оверрайд в корне проекта.
    paths_to_load = [CONFIG_PATH]
    for name in PROJECT_CONFIG_NAMES:
        candidate = root / name
        if candidate.is_file() and candidate.resolve() != CONFIG_PATH:
            paths_to_load.append(candidate)
            break

    merged = dict(DEFAULTS)
    loaded: list[Path] = []
    for path in paths_to_load:
        data = _read_json(path)
        if data:
            merged = deep_merge(merged, data)
            loaded.append(path)

    # 1-й проход: ${env:...} и ${agent_home}
    merged = expand_vars(merged, {"agent_home": str(AGENT_HOME)})

    # project_root уже решён — конфиги его не переопределяют.
    merged.setdefault("paths", {})["project_root"] = str(root)

    # 2-й проход: теперь доступен ${project_root}
    merged = expand_vars(merged, {
        "agent_home": str(AGENT_HOME),
        "agent_dir": str(AGENT_HOME),
        "project_root": str(root),
    })

    SETTINGS = merged
    API = merged.get("api", {})
    PATHS = merged.get("paths", {})
    SNAPSHOTS = merged.get("snapshots", {})
    AGENT_CFG = merged.get("agent", {})
    TOOLS_CFG = merged.get("tools", {})
    WEB = deep_merge(DEFAULTS["tools"]["web"], TOOLS_CFG.get("web") or {})
    PROJECT_ROOT = root
    LOADED_CONFIGS = loaded

    API_KEY = (
        os.environ.get(API.get("api_key_env") or "DEEPSEEK_API_KEY")
        or API.get("api_key")
        or ""
    )
    BASE_URL = API.get("base_url") or DEFAULTS["api"]["base_url"]
    MODEL = API.get("model") or DEFAULTS["api"]["model"]
    TEMPERATURE = float(API.get("temperature", DEFAULTS["api"]["temperature"]))
    CONTEXT_LIMIT = int(API.get("context_limit") or 0)
    MAX_BACKUPS = int(SNAPSHOTS.get("max_backups") or DEFAULTS["snapshots"]["max_backups"])
    MAX_STEPS = int(AGENT_CFG.get("max_steps") or DEFAULTS["agent"]["max_steps"])
    API_RETRIES = int(AGENT_CFG.get("api_retries") or DEFAULTS["agent"]["api_retries"])
    SHELL_TIMEOUT = int(TOOLS_CFG.get("shell_timeout") or DEFAULTS["tools"]["shell_timeout"])
    return root


def load_settings(path: str | os.PathLike | None = None) -> dict:
    """Читает один конфиг и раскрывает подстановки (без проектного оверрайда)."""
    cfg_path = Path(path) if path else CONFIG_PATH
    merged = deep_merge(DEFAULTS, _read_json(cfg_path))
    merged = expand_vars(merged, {"agent_home": str(AGENT_HOME)})

    raw_root = str((merged.get("paths") or {}).get("project_root") or "").strip()
    root = _normalize_path(raw_root, cfg_path.parent) if raw_root else Path.cwd().resolve()
    merged["paths"]["project_root"] = str(root)

    return expand_vars(merged, {
        "agent_home": str(AGENT_HOME),
        "agent_dir": str(AGENT_HOME),
        "project_root": str(root),
    })


# ---------- Константы (заполняются setup() при импорте) ----------

SETTINGS: dict = {}
API: dict = {}
PATHS: dict = {}
SNAPSHOTS: dict = {}
AGENT_CFG: dict = {}
TOOLS_CFG: dict = {}
WEB: dict = {}
PROJECT_ROOT: Path = Path.cwd()
API_KEY: str = ""
BASE_URL: str = ""
MODEL: str = ""
TEMPERATURE: float = 0.2
CONTEXT_LIMIT: int = 0
MAX_BACKUPS: int = 50
MAX_STEPS: int = 25
API_RETRIES: int = 3
SHELL_TIMEOUT: int = 60

setup()


# ---------- Помощники для ресурсов ----------

def agent_home() -> Path:
    """Папка с самим агентом (определена автоматически)."""
    return AGENT_HOME


def search_dirs(project_root: str | os.PathLike | None = None) -> list[Path]:
    """Порядок поиска общих ресурсов: проект, затем папка агента."""
    root = Path(project_root or PROJECT_ROOT)
    return [root] if root == AGENT_HOME else [root, AGENT_HOME]


def find_resource(relative: str, project_root: str | os.PathLike | None = None) -> Path | None:
    """Ищет файл/папку сначала в проекте, затем в AGENT_HOME."""
    path = Path(relative)
    if path.is_absolute():
        return path if path.exists() else None
    for base in search_dirs(project_root):
        candidate = base / path
        if candidate.exists():
            return candidate
    return None


def skills_candidates(project_root: str | os.PathLike | None = None) -> list[Path]:
    """Папки, где искать навыки (SKILL.md): проект, затем агент."""
    raw = PATHS.get("skills_dir") or DEFAULTS["paths"]["skills_dir"]
    path = Path(raw)
    if path.is_absolute():
        return [path]

    result: list[Path] = []
    for base in search_dirs(project_root):
        candidate = base / path
        if candidate not in result:
            result.append(candidate)
    return result


def plugins_candidates(project_root: str | os.PathLike | None = None) -> list[Path]:
    """Существующие папки плагинов/доп. модулей: проект, затем агент."""
    result: list[Path] = []
    for name in _as_list(PATHS.get("plugins_dirs") or DEFAULTS["paths"]["plugins_dirs"]):
        path = Path(name)
        candidates = [path] if path.is_absolute() else [
            base / path for base in search_dirs(project_root)
        ]
        for candidate in candidates:
            if candidate.is_dir() and candidate not in result:
                result.append(candidate)
    return result


def mcp_config_paths(project_root: str | os.PathLike | None = None) -> list[Path]:
    """Все найденные конфиги MCP-серверов: сначала проектные, затем агентские.

    paths.mcp_config может быть строкой или списком строк. Абсолютный путь
    используется как есть; относительный ищется в проекте и в AGENT_HOME.
    """
    raw = PATHS.get("mcp_config") or DEFAULTS["paths"]["mcp_config"]
    found: list[Path] = []

    for name in _as_list(raw):
        path = Path(name)
        candidates = [path] if path.is_absolute() else [
            base / path for base in search_dirs(project_root)
        ]
        for candidate in candidates:
            if candidate.is_file() and candidate not in found:
                found.append(candidate)
    return found


def mcp_config_path(project_root: str | os.PathLike | None = None) -> Path | None:
    """Первый (приоритетный) конфиг MCP. Оставлено для совместимости."""
    paths = mcp_config_paths(project_root)
    return paths[0] if paths else None


def backup_dir(project_root: str | os.PathLike | None = None) -> Path:
    """Каталог снапшотов. Относительный путь считается от проекта."""
    raw = PATHS.get("backup_dir") or DEFAULTS["paths"]["backup_dir"]
    path = Path(raw)
    return path if path.is_absolute() else Path(project_root or PROJECT_ROOT) / path


def max_backups() -> int:
    return MAX_BACKUPS


def max_steps() -> int:
    """Максимум шагов модели на одну задачу (защита от зацикливания)."""
    return MAX_STEPS


def api_retries() -> int:
    """Сколько раз повторять запрос к API при сбое."""
    return API_RETRIES


def shell_timeout() -> int:
    """Таймаут shell-команд в секундах."""
    return SHELL_TIMEOUT


def web_settings() -> dict:
    """Настройки встроенного веб-доступа (fetch_url / web_search)."""
    return WEB


def agent_home_path() -> Path:
    """Псевдоним agent_home() для ясности в новых модулях."""
    return AGENT_HOME


def cache_dir(project_root: str | os.PathLike | None = None) -> Path:
    """Папка служебных данных агента в проекте (.agent-cache).

    Внутри неё лежат backups/, history.txt и logs/.
    """
    backup = backup_dir(project_root)
    return backup.parent if backup.name == "backups" else Path(project_root or PROJECT_ROOT) / ".agent-cache"


def variables(project_root: str | os.PathLike | None = None) -> dict:
    """Словарь подстановок для MCP-конфигов и шаблонов."""
    root = Path(project_root or PROJECT_ROOT)
    return {
        "project_root": str(root),
        "agent_home": str(AGENT_HOME),
        "agent_dir": str(AGENT_HOME),
        "config": str(CONFIG_PATH),
        "backup_dir": str(backup_dir(root)),
        "skills_dir": str(root / (PATHS.get("skills_dir") or "skills")),
    }


def settings_summary() -> str:
    """Короткая сводка конфигурации для :config / :doctor."""
    loaded = ", ".join(str(p) for p in LOADED_CONFIGS) or "нет (только DEFAULTS)"
    mcp = mcp_config_paths() or ["не найден"]
    lines = [
        f"agent_home:    {AGENT_HOME}",
        f"project_root:  {PROJECT_ROOT}   (cwd: {Path.cwd()})",
        f"конфиги:       {loaded}",
        f"model:         {MODEL}",
        f"base_url:      {BASE_URL}",
        f"temperature:   {TEMPERATURE}",
        f"context_limit: {CONTEXT_LIMIT or '-'}",
        f"api_key:       {'задан' if API_KEY else 'НЕ задан'} "
        f"(env {API.get('api_key_env') or 'DEEPSEEK_API_KEY'})",
        f"skills_dir:    {', '.join(str(p) for p in skills_candidates()) or 'нет'}",
        f"mcp_config:    {', '.join(str(p) for p in mcp)}",
        f"backup_dir:    {backup_dir()} (max {MAX_BACKUPS})",
        f"max_steps:     {MAX_STEPS}   (повторов API при сбое: {API_RETRIES})",
        f"shell_timeout: {SHELL_TIMEOUT} c",
        f"web:           {'вкл' if WEB.get('enabled', True) else 'выкл'} "
        f"(timeout {WEB.get('timeout')} c, лимит {WEB.get('max_chars')} симв.)",
    ]
    plugins = plugins_candidates()
    if plugins:
        lines.append(f"plugins:       {', '.join(str(p) for p in plugins)}")
    return "\n".join(lines)
