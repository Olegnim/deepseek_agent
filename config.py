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
import logging
import os
import re
import sys
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
        # Thinking mode (https://api-docs.deepseek.com/guides/thinking_mode):
        # перед ответом модель выдаёт цепочку рассуждений (reasoning_content).
        # true/false — вкл/выкл; переключается командой :think.
        "thinking": True,
        # Усилие рассуждения: none / low / high / max. none = thinking выключен.
        # Допустимы алиасы API: minimal -> low, medium/xhigh -> high, ultra -> max.
        "reasoning_effort": "high",
        # Лимит токенов ответа. 0 = значение по умолчанию API
        # (8K без thinking, 64K с thinking, 128K при effort=max); максимум 384K.
        "max_tokens": 0,
        # nucleus sampling: 0 = не передавать. У deepseek-flash действует только
        # в thinking mode (эффективный диапазон 0.95–1.0).
        "top_p": 0,
        # Стриминг (stream=true): ответ печатается по мере генерации.
        # По умолчанию false — ждём ответ целиком: виден спиннер «DeepSeek
        # думает» и ответ форматируется (markdown) в терминале.
        # Переключается командой :stream on|off.
        "stream": False,
    },
    # Изображения (https://api-docs.deepseek.com/guides/vision): инструмент
    # read_image отправляет картинку модели как image_url (base64 data URL).
    "vision": {
        "enabled": True,
        # Лимит файла: inline base64 ограничен 32 МиБ на изображение.
        "max_bytes": 8 * 1024 * 1024,
        # low / high / original / auto — как в документации (low = 512x512).
        "detail": "auto",
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
        # Папки плагинов: .py-файлы с функцией register(api) добавляют агенту
        # свои инструменты (см. plugins_loader.py). Пусто — без плагинов.
        "plugins_dirs": ["plugins"],    },
    # MCP: какие папки агент объявляет серверам как «корни» (roots/list).
    "mcp": {
        # Пусто = только paths.project_root. Пути можно задавать относительно
        # проекта; подстановка ${project_root} работает.
        "roots": [],
    },
    "snapshots": {
        "max_backups": 50,
    },
    "cache": {
        # Спрашивать при старте интерактивного режима, очищать ли кэш
        # (.agent-cache: снапшоты, логи, история ввода).
        "ask_on_start": True,
    },
    "agent": {
        # Максимум шагов модели (запросов к API) на одну задачу.
        # 0 или меньше = без ограничений (по умолчанию): задачу не обрывает,
        # а от зацикливания защищает agent.loop_guard (см. ниже).
        "max_steps": 0,
        # Сколько раз повторять запрос к API при сетевой ошибке/429.
        "api_retries": 3,
        # Язык ответов агента (подставляется в системный промпт).
        "language": "русском",
        # Профиль (роль) агента: имя из секции "profiles" (php, python, frontend, ...).
        # Пусто = авто: навыки выбираются по стеку проекта. Переключается флагом
        # --profile или командой :profile.
        "profile": "",
        # Защита от зацикливания: одинаковый вызов инструмента с тем же
        # результатом подряд. Работает и при max_steps = 0.
        "loop_guard": {
            "enabled": True,
            # Сколько одинаковых вызовов подряд считать циклом (0 = выключить).
            "repeat_limit": 3,
        },
        # Дополнительные инструкции агента: строка или список строк.
        # Так проект задаёт свои правила, не трогая код агента.
        "instructions": [],
    },
    # Профили (роли) агента: какой набор навыков подключать и что дополнительно
    # сказать модели. Выбор: agent.profile, флаг --profile, команда :profile.
    # Свои профили (любой язык/фреймворк) добавляются в agent.config.json —
    # код агента менять не нужно.
    "profiles": {
        "php": {
            "description": "PHP-разработчик (веб-приложения)",
            "skills": ["code-quality", "php-conventions", "php-web"],
            "instructions": [],
        },
        "python": {
            "description": "Python-разработчик",
            "skills": ["code-quality", "python-conventions"],
            "instructions": [],
        },
        "frontend": {
            "description": "Фронтенд-разработчик (HTML/CSS/JS/TS)",
            "skills": ["code-quality", "web-frontend"],
            "instructions": [],
        },
    },
    # Автолинтер: проверка синтаксиса файла сразу после write_file/edit_file.
    # {file} — плейсхолдер пути к проверяемому файлу (в кавычках).
    "lint": {
        "enabled": True,
        "timeout": 30,
        "rules": [
            {"ext": [".php", ".phtml"], "command": "php -l {file}", "label": "php -l"},
            {"ext": [".js", ".mjs", ".cjs"], "command": "node --check {file}",
             "label": "node --check"},
            {"ext": [".py"], "command": "python -m py_compile {file}",
             "label": "python -m py_compile"},
            # Java: только разбор (без генерации .class) — быстро и без артефактов.
            {"ext": [".java"], "command": "javac -proc:only {file}",
             "label": "javac -proc:only"},
            # Kotlin: kotlinc не умеет «только разбор», но кладём вывод в кэш,
            # чтобы не мусорить в дереве проекта (каталог .agent-cache игнорируется).
            {"ext": [".kt", ".kts"],
             "command": "kotlinc {file} -d .agent-cache/lint-kotlin",
             "label": "kotlinc"},
            # Swift: -parse разбирает файл без типизации и без записи файлов.
            {"ext": [".swift"], "command": "swiftc -parse {file}",
             "label": "swiftc -parse"},
            # Go: gofmt -e сообщает все синтаксические ошибки (на успехе печатает
            # отформатированный текст в stdout — он не попадает в ответ модели).
            {"ext": [".go"], "command": "gofmt -e {file}", "label": "gofmt -e"},
            # Ruby: ruby -c — только проверка синтаксиса, без выполнения кода.
            {"ext": [".rb"], "command": "ruby -c {file}", "label": "ruby -c"},
        ],
    },
    "tools": {
        # Таймаут shell-команд, секунды.
        "shell_timeout": 60,
        # Встроенный доступ в интернет (tools/web.py): fetch_url + web_search.
        "web": {
            "enabled": True,
            "timeout": 20,         # таймаут одного HTTP-запроса, сек
            "max_chars": 20000,    # сколько символов страницы отдавать модели
            "results": 5,          # сколько результатов поиска возвращать
            "excerpt_paragraphs": 8,   # фрагментов при fetch_url(query=...)
        },
        # Бюджет вывода инструментов (tools/digest.py): модель получает выжимку,
        # полный вывод сохраняется в .agent-cache/output и читается точечно.
        "output": {
            "enabled": True,
            "max_chars": 6000,     # сколько символов результата уходит в контекст
            "head_lines": 25,      # сколько первых строк оставлять
            "tail_lines": 15,      # сколько последних строк оставлять
            "keep_files": 40,      # сколько сохранённых выводов хранить
            # Инструменты, к которым выжимка не применяется: они уже ограничены
            # своими лимитами, и модель явно попросила их содержимое.
            "no_digest": ["read_file", "read_range"],
        },
        # Поиск и навигация по коду (tools/search.py).
        "search": {
            "max_results": 60,     # сколько совпадений/строк показывать
            "context": 0,          # строк контекста вокруг совпадения
            "max_files": 5000,     # сколько файлов максимум просматривать
        },
    },
    # Мост к расширению VS Code (vscode-extension/): агент открывает и закрывает
    # файлы прямо в редакторе, поэтому видно, с чем он работает. Расширение
    # поднимает локальный HTTP-сервер на 127.0.0.1 и пишет порт с токеном в
    # <project>/.agent-cache/vscode-bridge.json.
    "vscode": {
        # Выключено — инструменты vscode_* не показываются модели вообще.
        "enabled": True,
        # Открывать правленный файл в редакторе после write_file / edit_file.
        "auto_open": True,
        # Перед открытием нового файла закрывать вкладку, открытую агентом ранее.
        "auto_close_previous": False,
        # Таймаут HTTP-запроса к мосту, секунды.
        "timeout": 5,
        # На старте интерактивного режима: если моста нет, запустить VS Code с
        # проектом (CLI `code`) и дождаться, пока расширение поднимет мост.
        "auto_start": True,
        # Сколько секунд ждать мост после запуска VS Code.
        "start_wait": 8,
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


# Ветки реестра Windows, где лежат «постоянные» переменные окружения.
_WIN_ENV_LOCATIONS = (
    ("HKEY_CURRENT_USER", r"Environment"),
    ("HKEY_LOCAL_MACHINE",
     r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
)


def env_value(name: str, default: str = "") -> str:
    """Значение переменной окружения с запасным чтением из реестра Windows.

    `setx` (и «Параметры системы → Переменные среды») пишут переменную в реестр,
    но уже запущенные процессы — терминал, VS Code, python — её не видят до
    перезапуска. Поэтому если в os.environ значения нет, на Windows читаем
    ветки HKCU\\Environment и системную. Так ключ подхватывается сразу.
    """
    value = os.environ.get(name)
    if value:
        return value
    if os.name != "nt":
        return default
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows без winreg не бывает
        return default
    for hive_name, subkey in _WIN_ENV_LOCATIONS:
        try:
            with winreg.OpenKey(getattr(winreg, hive_name), subkey) as key:
                raw, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if raw:
            text = os.path.expandvars(str(raw))  # REG_EXPAND_SZ: %SystemRoot% и т.п.
            logging.debug("%s: значение взято из реестра Windows", name)
            return text
    return default


def expand_vars(value, variables: dict, keep: tuple[str, ...] = ()) -> object:
    """Раскрывает ${env:VAR}, ${agent_home}, ${project_root} в строках/списках/dict.

    keep — имена подстановок, которые на этом проходе ещё не вычислены:
    они остаются в строке как есть (например, ${project_root} на первом
    проходе), а не превращаются в пустую строку. Неизвестные имена по-прежнему
    дают пустую строку, чтобы битый конфиг не ронял загрузку.
    """
    variables = variables or {}
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            key = match.group(1).strip()
            if key.startswith("env:"):
                return env_value(key[4:].strip())
            if key == "agent_dir":
                key = "agent_home"
            if key in variables:
                return str(variables[key])
            if key in keep:
                return match.group(0)
            return ""

        return _VAR_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: expand_vars(v, variables, keep) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_vars(v, variables, keep) for v in value]
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


_TOKEN_SUFFIXES = {"k": 1_000, "m": 1_000_000, "g": 1_000_000_000}


def parse_token_count(value) -> int:
    """Токены из конфига: число или строка с суффиксом (65536, "128k", "1M").

    Некорректное значение даёт 0 — «лимит неизвестен», агент продолжит работу.
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace("_", "").replace(" ", "")
    if not text:
        return 0
    suffix = text[-1].lower()
    if suffix in _TOKEN_SUFFIXES:
        text, multiplier = text[:-1], _TOKEN_SUFFIXES[suffix]
    else:
        multiplier = 1
    try:
        return int(float(text) * multiplier)
    except ValueError:
        logging.warning("context_limit: не удалось разобрать %r", value)
        return 0


def fmt_tokens(count: int) -> str:
    """Число токенов с разделителями разрядов: 1000000 -> '1 000 000'."""
    return f"{int(count):,}".replace(",", " ")


# ---------- Определение корня проекта ----------

def resolve_project_root(cli_root: str | None = None) -> Path:
    """Вычисляет корень проекта по приоритету:

        -p  >  DEEPSEEK_PROJECT_ROOT  >  конфиг в cwd  >  конфиг агента  >  cwd
    """
    if cli_root:
        return _normalize_path(cli_root, Path.cwd())

    env_root = (env_value("DEEPSEEK_PROJECT_ROOT") or "").strip()
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

def _flag(value, default: bool = True) -> bool:
    """Приводит значение из конфига к bool: true/false, on/off, 1/0, да/нет."""
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return default
        return text not in ("false", "off", "0", "no", "none", "disabled")
    return bool(value)


def setup(cli_project_root: str | None = None) -> Path:
    """Определяет PROJECT_ROOT, читает конфиги и обновляет константы модуля.

    Вызывается автоматически при импорте и повторно из agent.main() (когда
    передан флаг -p или нужен свежий расчёт после смены cwd).
    """
    global SETTINGS, API, PATHS, SNAPSHOTS, CACHE, AGENT_CFG, TOOLS_CFG, WEB, LINT
    global PROFILES, LOOP_GUARD, VSCODE, MCP_CFG, VISION, OUTPUT, SEARCH
    global PROJECT_ROOT, LOADED_CONFIGS
    global API_KEY, BASE_URL, MODEL, TEMPERATURE, CONTEXT_LIMIT, MAX_BACKUPS
    global MAX_STEPS, API_RETRIES, SHELL_TIMEOUT, MAX_OUTPUT_TOKENS, TOP_P, STREAM

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
    files_data: list[dict] = []          # то, что реально прочитано из файлов
    for path in paths_to_load:
        data = _read_json(path)
        if data:
            files_data.append(data)
            merged = deep_merge(merged, data)
            loaded.append(path)

    # 1-й проход: ${env:...} и ${agent_home}; ${project_root} пока не известен,
    # поэтому его оставляем как есть — раскроется на втором проходе.
    merged = expand_vars(merged, {"agent_home": str(AGENT_HOME)},
                         keep=("project_root",))

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
    CACHE = merged.get("cache", {})
    AGENT_CFG = merged.get("agent", {})
    TOOLS_CFG = merged.get("tools", {})
    WEB = deep_merge(DEFAULTS["tools"]["web"], TOOLS_CFG.get("web") or {})
    # Бюджет вывода инструментов: сколько символов результата видит модель.
    OUTPUT = deep_merge(DEFAULTS["tools"]["output"], TOOLS_CFG.get("output") or {})
    # Поиск по коду (tools/search.py).
    SEARCH = deep_merge(DEFAULTS["tools"]["search"], TOOLS_CFG.get("search") or {})
    # Интеграция с редактором VS Code (секция "vscode" верхнего уровня).
    VSCODE = deep_merge(DEFAULTS["vscode"], merged.get("vscode") or {})
    # Передача изображений модели (секция "vision" верхнего уровня).
    VISION = deep_merge(DEFAULTS["vision"], merged.get("vision") or {})
    # Корни MCP (roots/list): какие папки агент отдаёт серверам как разрешённые.
    MCP_CFG = deep_merge(DEFAULTS["mcp"], merged.get("mcp") or {})
    # Автолинтер: секция "lint" верхнего уровня или tools.lint (оба варианта).
    # Берём только то, что реально задано в файлах: у DEFAULTS секция lint есть
    # всегда, поэтому merged.get("lint") перекрыл бы tools.lint и устаревший
    # вариант конфига не работал бы.
    lint_explicit: dict = {}
    for data in files_data:
        tools_lint = (data.get("tools") or {}).get("lint")
        if isinstance(tools_lint, dict):
            lint_explicit = deep_merge(lint_explicit, tools_lint)
        top_lint = data.get("lint")
        if isinstance(top_lint, dict):
            lint_explicit = deep_merge(lint_explicit, top_lint)
    LINT = deep_merge(DEFAULTS["lint"], lint_explicit)
    PROJECT_ROOT = root
    LOADED_CONFIGS = loaded

    API_KEY = (
        env_value(API.get("api_key_env") or "DEEPSEEK_API_KEY")
        or API.get("api_key")
        or ""
    )
    # Пустая строка -> "" (для :doctor и подсказок видно, что ключа нет).
    API_KEY = API_KEY.strip()
    BASE_URL = API.get("base_url") or DEFAULTS["api"]["base_url"]
    MODEL = API.get("model") or DEFAULTS["api"]["model"]
    TEMPERATURE = float(API.get("temperature", DEFAULTS["api"]["temperature"]))
    CONTEXT_LIMIT = parse_token_count(API.get("context_limit"))
    # Лимит токенов ответа: 0 = не передавать (действует значение API).
    # Больше 393216 API не принимает (384K) — ограничиваем заранее.
    # parse_token_count понимает и число, и строку с суффиксом ("64k", "128k").
    MAX_OUTPUT_TOKENS = max(0, min(parse_token_count(API.get("max_tokens")), 393216))
    TOP_P = float(API.get("top_p") or 0)
    STREAM = _flag(API.get("stream", DEFAULTS["api"]["stream"]))
    MAX_BACKUPS = int(SNAPSHOTS.get("max_backups") or DEFAULTS["snapshots"]["max_backups"])
    raw_steps = AGENT_CFG.get("max_steps")
    MAX_STEPS = int(
        DEFAULTS["agent"]["max_steps"] if raw_steps is None else raw_steps
    )
    LOOP_GUARD = deep_merge(
        DEFAULTS["agent"]["loop_guard"], AGENT_CFG.get("loop_guard") or {}
    )
    # Ключи с "_" в секции profiles — служебные пояснения конфига: в PROFILES
    # их не держим, чтобы внешний код и плагины могли безопасно перебирать профили.
    raw_profiles = merged.get("profiles") or DEFAULTS["profiles"]
    PROFILES = {name: cfg for name, cfg in raw_profiles.items()
                if not str(name).startswith("_")} or DEFAULTS["profiles"]
    API_RETRIES = int(AGENT_CFG.get("api_retries") or DEFAULTS["agent"]["api_retries"])
    SHELL_TIMEOUT = int(TOOLS_CFG.get("shell_timeout") or DEFAULTS["tools"]["shell_timeout"])
    return root


# ---------- Константы (заполняются setup() при импорте) ----------

SETTINGS: dict = {}
API: dict = {}
PATHS: dict = {}
SNAPSHOTS: dict = {}
CACHE: dict = {}
AGENT_CFG: dict = {}
TOOLS_CFG: dict = {}
WEB: dict = {}
VSCODE: dict = {}
LINT: dict = {}
MCP_CFG: dict = {}
PROFILES: dict = {}
LOOP_GUARD: dict = {}
VISION: dict = {}
# Переопределение профиля на время сессии (флаг --profile / команда :profile).
_PROFILE_OVERRIDE: str | None = None
# Переопределения thinking mode на время сессии (команда :think).
_THINKING_OVERRIDE: bool | None = None
_EFFORT_OVERRIDE: str | None = None
# Переопределение стриминга на время сессии (команда :stream).
_STREAM_OVERRIDE: bool | None = None
PROJECT_ROOT: Path = Path.cwd()
API_KEY: str = ""
BASE_URL: str = ""
MODEL: str = ""
TEMPERATURE: float = 0.2
CONTEXT_LIMIT: int = 0
MAX_BACKUPS: int = 50
MAX_STEPS: int = 0
API_RETRIES: int = 3
SHELL_TIMEOUT: int = 60
MAX_OUTPUT_TOKENS: int = 0
STREAM: bool = False
TOP_P: float = 0.0

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
    """Ищет файл/папку сначала в проекте, затем в AGENT_HOME.

    Публичный хелпер: используется плагинами (`plugins_loader.PluginAPI`),
    чтобы достать свой ресурс (схему, шаблон) из папки проекта или агента.
    """
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


def mcp_roots(project_root: str | os.PathLike | None = None) -> list[Path]:
    """Папки, которые агент объявляет MCP-серверам как «корни» (roots/list).

    Берётся секция `mcp.roots` из конфига; пустая (по умолчанию) — значит
    единственный корень это сам проект. Относительные пути считаются от
    корня проекта, `~` и `${project_root}` раскрываются как везде.
    Если в конфиге заданы только несуществующие пути, возвращается проект —
    иначе сервер остался бы без разрешённых папок.
    """
    root = Path(project_root or PROJECT_ROOT).resolve()
    raw = MCP_CFG.get("roots") if MCP_CFG else None
    if not isinstance(raw, (list, tuple, str)):
        raw = None
    result: list[Path] = []
    for item in _as_list(raw):
        value = str(item).strip()
        if not value:
            continue
        path = _normalize_path(value, root)
        if path not in result:
            result.append(path)
    return result or [root]


def backup_dir(project_root: str | os.PathLike | None = None) -> Path:
    """Каталог снапшотов. Относительный путь считается от проекта."""
    raw = PATHS.get("backup_dir") or DEFAULTS["paths"]["backup_dir"]
    path = Path(raw)
    return path if path.is_absolute() else Path(project_root or PROJECT_ROOT) / path


def max_backups() -> int:
    return MAX_BACKUPS


def ask_cache_on_start() -> bool:
    """Спрашивать ли при старте, очищать ли кэш проекта."""
    return bool(CACHE.get("ask_on_start", DEFAULTS["cache"]["ask_on_start"]))


def max_steps() -> int:
    """Максимум шагов модели на одну задачу.

    0 или меньше означает «без ограничений» (проверяется в agent._run_loop);
    от зацикливания в этом режиме защищает loop_guard_settings().
    """
    return MAX_STEPS


def loop_guard_settings() -> dict:
    """Настройки защиты от зацикливания (секция agent.loop_guard)."""
    return LOOP_GUARD


def profiles() -> dict:
    """Доступные профили (роли) агента: {имя: {description, skills, instructions}}.

    Встроенные профили заданы в DEFAULTS, свои добавляются секцией "profiles"
    в agent.config.json (ключи, начинающиеся с "_", — служебные пояснения).
    """
    return {
        name: cfg for name, cfg in (PROFILES or {}).items()
        if not name.startswith("_") and isinstance(cfg, dict)
    }


def profile_names() -> list[str]:
    """Имена доступных профилей (для справки и валидации)."""
    return sorted(profiles())


def agent_profile() -> str:
    """Имя активного профиля: переопределение сессии > конфиг > "" (авто)."""
    if _PROFILE_OVERRIDE is not None:
        return _PROFILE_OVERRIDE
    return str(AGENT_CFG.get("profile") or "").strip().lower()


def set_profile(name: str | None) -> str:
    """Переключает профиль на время сессии (флаг --profile, команда :profile).

    None — снять переопределение (вернуться к значению из конфига);
    "", "auto", "none", "off" — авто по стеку проекта.
    """
    global _PROFILE_OVERRIDE
    if name is None:
        _PROFILE_OVERRIDE = None
    else:
        value = str(name).strip().lower()
        _PROFILE_OVERRIDE = "" if value in ("", "auto", "none", "off") else value
    return agent_profile()


def active_profile() -> dict:
    """Разобранный активный профиль или {} (авто / неизвестное имя).

    Возвращает {"name", "description", "skills", "instructions"}.
    """
    name = agent_profile()
    if not name:
        return {}
    cfg = profiles().get(name)
    if not cfg:
        return {}
    skills = _as_list(cfg.get("skills"))
    return {
        "name": name,
        "description": str(cfg.get("description") or name),
        "skills": skills,
        "instructions": _as_list(cfg.get("instructions")),
    }


def api_retries() -> int:
    """Сколько раз повторять запрос к API при сбое."""
    return API_RETRIES


def shell_timeout() -> int:
    """Таймаут shell-команд в секундах."""
    return SHELL_TIMEOUT


# ---------- Thinking mode и параметры генерации ----------

# API принимает не только точные значения, но и алиасы (см. Thinking Mode).
EFFORT_ALIASES = {
    "minimal": "low",
    "medium": "high",
    "xhigh": "high",
    "ultra": "max",
}
EFFORT_VALUES = ("none", "low", "high", "max")


def normalize_reasoning_effort(value) -> str:
    """Приводит усилие рассуждения к none/low/high/max (алиасы API понимаются).

    Неизвестное значение -> high (усилие по умолчанию в API).
    """
    effort = str(value if value is not None else "").strip().lower()
    if effort in ("off", "disabled", "false", "no"):
        return "none"
    if effort in ("on", "enabled", "true", "yes"):
        return "high"
    effort = EFFORT_ALIASES.get(effort, effort)
    return effort if effort in EFFORT_VALUES else "high"


def _flag(value, default: bool = True) -> bool:
    """Приводит значение из конфига к bool: true/false, on/off, 1/0, да/нет."""
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return default
        return text not in ("false", "off", "0", "no", "none", "disabled")
    return bool(value)


def _config_thinking_enabled() -> bool:
    """Значение api.thinking из конфига (bool или строка enabled/disabled)."""
    return _flag(API.get("thinking", DEFAULTS["api"]["thinking"]))


def reasoning_effort() -> str:
    """Текущее усилие рассуждения (none/low/high/max) с учётом :think."""
    if _EFFORT_OVERRIDE is not None:
        return _EFFORT_OVERRIDE
    return normalize_reasoning_effort(
        API.get("reasoning_effort", DEFAULTS["api"]["reasoning_effort"])
    )


def thinking_enabled() -> bool:
    """Включён ли thinking mode (effort=none его выключает)."""
    if reasoning_effort() == "none":
        return False
    if _THINKING_OVERRIDE is not None:
        return _THINKING_OVERRIDE
    return _config_thinking_enabled()


def set_thinking(value) -> bool:
    """Переключает thinking mode на время сессии (команда :think on|off).

    None — снять переопределение (вернуться к конфигу).
    """
    global _THINKING_OVERRIDE, _EFFORT_OVERRIDE
    if value is None:
        _THINKING_OVERRIDE = None
        return thinking_enabled()
    enabled = normalize_reasoning_effort(value) != "none"
    _THINKING_OVERRIDE = enabled
    if not enabled:
        # effort=none в API тоже означает «без рассуждений».
        _EFFORT_OVERRIDE = "none"
    elif _EFFORT_OVERRIDE == "none":
        _EFFORT_OVERRIDE = None          # вернуть усилие из конфига
    return enabled


def set_reasoning_effort(value) -> str:
    """Меняет усилие рассуждения на время сессии (команда :think low|high|max).

    None — снять переопределение.
    """
    global _EFFORT_OVERRIDE, _THINKING_OVERRIDE
    if value is None:
        _EFFORT_OVERRIDE = None
        return reasoning_effort()
    effort = normalize_reasoning_effort(value)
    _EFFORT_OVERRIDE = effort
    if effort != "none":
        _THINKING_OVERRIDE = True
    return effort


def thinking_summary() -> str:
    """Строка про thinking mode для :config / :doctor / :think."""
    mode = "вкл" if thinking_enabled() else "выкл"
    if not thinking_enabled():
        return f"{mode} (рассуждения отключены, temperature работает)"
    return f"{mode} (усилие: {reasoning_effort()})"


def max_output_tokens() -> int:
    """Лимит токенов ответа из api.max_tokens (0 = значение по умолчанию API)."""
    return MAX_OUTPUT_TOKENS


def api_top_p() -> float:
    """top_p из api.top_p (0 = не передавать параметр)."""
    return TOP_P


def stream_enabled() -> bool:
    """Стримится ли ответ модели (api.stream, переключается командой :stream)."""
    if _STREAM_OVERRIDE is not None:
        return _STREAM_OVERRIDE
    return STREAM


def set_stream(value) -> bool:
    """Переключает стриминг на время сессии (команда :stream on|off).

    None — снять переопределение (вернуться к значению из конфига).
    """
    global _STREAM_OVERRIDE
    _STREAM_OVERRIDE = None if value is None else _flag(value)
    return stream_enabled()


def stream_summary() -> str:
    """Строка про стриминг для :config / :stream."""
    if stream_enabled():
        return "вкл (текст печатается по мере генерации)"
    return "выкл (ждать ответ целиком)"


def vision_settings() -> dict:
    """Настройки передачи изображений модели (секция "vision")."""
    return VISION


# ---------- Python-интерпретатор: кросс-платформенные команды ----------

def python_exe() -> str:
    """Путь к интерпретатору Python, которым запущен сам агент.

    Команда `python` есть не везде (на macOS и Debian/Ubuntu обычно только
    `python3`), а `py` — только на Windows. Поэтому все Python-команды,
    которые агент показывает модели и выполняет сам (автолинт, тесты),
    строятся от sys.executable — рабочая команда на любой ОС.
    """
    return sys.executable or "python"


def python_command(*args: str) -> str:
    """Команда запуска Python с аргументами, готовая для run_shell.

    Пример: python_command("-m", "pytest") ->
            '"<путь>/python3" -m pytest'   (в Windows — '...\\python.exe').
    """
    parts = [f'"{python_exe()}"']
    parts += [f'"{a}"' if " " in str(a) else str(a) for a in args]
    return " ".join(parts)


def python_hint() -> str:
    """Подсказка про интерпретатор Python для системного промпта и :doctor.

    Без неё модель пишет `python -m pytest`, что не работает на macOS/Linux,
    где команды `python` может не быть.
    """
    exe = python_exe()
    name = Path(exe).name or "python"
    return (f'Интерпретатор Python этой системы: "{exe}" (команда `{name}`). '
            f"Python-команды запускай от него: тесты — "
            f"run_shell('{python_command('-m', 'pytest')}'), "
            f"пример из правил автолинта — "
            f"run_shell('{python_command('-m', 'py_compile', 'путь/файл.py')}').")


# Первое слово команды: в кавычках ("C:/Program Files/Python/python.exe") или без.
_CMD_SPLIT_RE = re.compile(r"""\s*("([^"]*)"|'([^']*)'|(\S+))(?:\s+(.*))?$""",
                           re.DOTALL)


def split_command(command: str) -> tuple[str, str]:
    """Делит команду на программу и остаток: ('python', '-m pytest').

    Кавычки учитываются, поэтому путь с пробелами
    (`"C:/Program Files/Python/python.exe" -m py_compile a.py`) разбирается
    правильно — именно такой вид даёт `python_command()` и правила автолинта.
    Раньше деление шло по первому пробелу, и такой путь распознавался как
    «python» со «остатком» `/Program Files/...`, то есть команда ломалась.
    """
    text = (command or "").strip()
    match = _CMD_SPLIT_RE.match(text)
    if not match:
        return text, ""
    program = match.group(2) or match.group(3) or match.group(4) or ""
    return program, (match.group(5) or "").strip()


def is_python_command(command: str) -> bool:
    """Команда запускает Python: python / python3 / py (в т.ч. с путём и .exe)?

    Понимает кавычки, полный путь и пути с пробелами, например
    `"C:/Python311/python.exe" -V` или
    `"C:/Program Files/Python/python.exe" -V` или `'python3 -m pytest'`.
    """
    program, _ = split_command(command)
    if not program:
        return False
    name = Path(program).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name in {"python", "python3", "py"}


def lint_settings() -> dict:
    """Настройки автолинтера (секция "lint" в agent.config.json)."""
    return LINT


def agent_language() -> str:
    """Язык ответов агента (подставляется в системный промпт)."""
    return str(AGENT_CFG.get("language") or DEFAULTS["agent"]["language"])


def agent_instructions() -> str:
    """Дополнительные инструкции проекта: строка или список строк.

    Позволяют задать правила «под проект», не трогая код агента.
    """
    raw = AGENT_CFG.get("instructions")
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        return "\n".join(
            f"- {str(item).strip()}" for item in raw if str(item).strip()
        )
    return ""


def web_settings() -> dict:
    """Настройки встроенного веб-доступа (fetch_url / web_search)."""
    return WEB


def output_settings() -> dict:
    """Бюджет вывода инструментов (tools.output): выжимка вместо простыни."""
    return OUTPUT


def search_settings() -> dict:
    """Настройки поиска по коду (tools.search)."""
    return SEARCH


def vscode_settings() -> dict:
    """Настройки моста к расширению VS Code (секция "vscode")."""
    return VSCODE


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


def _loop_guard_summary() -> str:
    """Строка про защиту от зацикливания для сводки настроек."""
    limit = int(LOOP_GUARD.get("repeat_limit") or 0)
    if not LOOP_GUARD.get("enabled", True) or limit <= 0:
        return "выкл"
    return f"вкл (стоп после {limit} одинаковых вызовов подряд)"


def _profile_summary() -> str:
    """Строка про активный профиль для сводки настроек."""
    name = agent_profile()
    if not name:
        return "авто (навыки по стеку проекта)"
    profile = active_profile()
    if not profile:
        return (f"{name} — НЕ НАЙДЕН в секции profiles "
                f"(доступны: {', '.join(profile_names()) or 'нет'})")
    return (f"{name} — {profile['description']} "
            f"(навыки: {', '.join(profile['skills']) or '—'})")


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
        f"thinking:      {thinking_summary()}",
        f"max_tokens:    {MAX_OUTPUT_TOKENS or 'по умолчанию API (8K / 64K)'}",
        f"top_p:         {TOP_P or 'не передаётся'}",
        f"stream:        {stream_summary()}",
        f"context_limit: {fmt_tokens(CONTEXT_LIMIT) if CONTEXT_LIMIT else '-'}",
        f"api_key:       {'задан' if API_KEY else 'НЕ задан'} "
        f"(env {API.get('api_key_env') or 'DEEPSEEK_API_KEY'})",
        f"skills_dir:    {', '.join(str(p) for p in skills_candidates()) or 'нет'}",
        f"mcp_config:    {', '.join(str(p) for p in mcp)}",
        f"mcp_roots:     {', '.join(str(p) for p in mcp_roots())}",
        f"backup_dir:    {backup_dir()} (max {MAX_BACKUPS})",
        f"max_steps:     {'без ограничений' if MAX_STEPS <= 0 else MAX_STEPS}   "
        f"(повторов API при сбое: {API_RETRIES})",
        f"loop-guard:    {_loop_guard_summary()}",
        f"shell_timeout: {SHELL_TIMEOUT} c",
        f"language:      {agent_language()}",
        f"profile:       {_profile_summary()}",
        f"lint:          {'вкл' if LINT.get('enabled', True) else 'выкл'} "
        f"({len(LINT.get('rules') or [])} правил, таймаут {LINT.get('timeout')} c)",
        f"web:           {'вкл' if WEB.get('enabled', True) else 'выкл'} "
        f"(timeout {WEB.get('timeout')} c, лимит {WEB.get('max_chars')} симв.)",
        f"вывод:         {'вкл' if OUTPUT.get('enabled', True) else 'выкл'} "
        f"(бюджет {OUTPUT.get('max_chars')} симв., первые/последние строки "
        f"{OUTPUT.get('head_lines')}/{OUTPUT.get('tail_lines')}, "
        f"храним выводов: {OUTPUT.get('keep_files')})",
        f"поиск:         до {SEARCH.get('max_results')} совпадений, "
        f"контекст {SEARCH.get('context')} строк, файлов до {SEARCH.get('max_files')}",
        f"vision:        {'вкл' if VISION.get('enabled', True) else 'выкл'} "
        f"(detail {VISION.get('detail')}, лимит файла "
        f"{int(VISION.get('max_bytes') or 0) // (1024 * 1024)} МиБ)",
        f"vscode:        {'вкл' if VSCODE.get('enabled', True) else 'выкл'} "
        f"(авто-открытие правок: {'да' if VSCODE.get('auto_open', True) else 'нет'}, "
        f"автозапуск редактора: {'да' if VSCODE.get('auto_start', True) else 'нет'})",
    ]
    plugins = plugins_candidates()
    if plugins:
        lines.append(f"plugins:       {', '.join(str(p) for p in plugins)}")
    return "\n".join(lines)
