"""
DeepSeek CLI Agent — универсальный помощник по коду (PHP, Python, JS/TS, веб).

Возможности:
- работа с конкретным проектом (--project-root);
- автоопределение стека проекта (composer.json, package.json, pyproject.toml, ...);
- профили (роли) агента: --profile php / python / frontend или свои из секции
  "profiles" в конфиге (привязывают агента к нужному набору навыков);
- правила под проект через навыки (skills) и agent.instructions в конфиге;
- автолинтер: проверка синтаксиса файла сразу после write_file/edit_file;
- шаги без лимита (agent.max_steps = 0) + loop-guard: защита от зацикливания
  на повторяющемся действии;
- подтверждение опасных операций;
- мягкое планирование: PLAN.md, одно подтверждение и автопилот (:plan, PLAN_MODE);
- автоснапшоты файлов перед правкой (.agent-cache/backups/);
- MCP-серверы через mcp_config.json;
- возможности API: режим рассуждений (api.thinking / reasoning_effort, команда
  :think), лимит ответа (api.max_tokens), передача изображений модели
  (read_image, секция vision), стриминг ответа (api.stream / команда :stream);
- интерактивный REPL с командами (:help, :tokens, :context, :restore, ...);
- спиннер, цветной вывод, статистика токенов и размера контекста.

Никаких зашитых под конкретный язык правил здесь нет: язык, стек и проверки
описываются в скиллах (skills/*/SKILL.md), профилях, секции "lint" и
agent.instructions файла agent.config.json.
"""

import re
import os
import sys
import json
import time
import shutil
import platform
import argparse
import asyncio
import unicodedata
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from openai import OpenAI

# Консоль Windows по умолчанию cp1251 — без этого падают символы ✓/✗ и эмодзи.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# --- UI: rich (опционально) ---
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text
    from rich.errors import MarkupError
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None
    MarkupError = ValueError     # чтобы except ниже работал без rich

# --- UI: prompt_toolkit (опционально) ---
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.patch_stdout import patch_stdout
    HAS_PT = True
except ImportError:
    HAS_PT = False

import config as app_config
from config import (
    CONFIG_PATH,
    agent_home,
    backup_dir,
    cache_dir,
    mcp_config_paths,
    mcp_roots,
    plugins_candidates,
    skills_candidates,
    settings_summary,
    variables as config_variables,
    setup as config_setup,
    max_steps as config_max_steps,
    api_retries as config_api_retries,
    web_settings as config_web_settings,
    output_settings as config_output_settings,
    vision_settings as config_vision_settings,
    thinking_enabled as config_thinking_enabled,
    reasoning_effort as config_reasoning_effort,
    thinking_summary as config_thinking_summary,
    set_thinking as config_set_thinking,
    set_reasoning_effort as config_set_reasoning_effort,
    max_output_tokens as config_max_output_tokens,
    api_top_p as config_api_top_p,
    stream_enabled as config_stream_enabled,
    set_stream as config_set_stream,
    stream_summary as config_stream_summary,
    ask_cache_on_start as config_ask_cache_on_start,
    agent_language as config_agent_language,
    agent_instructions as config_agent_instructions,
    lint_settings as config_lint_settings,
)
from tools import TOOLS, REGISTRY, WEB_TOOLS, GIT_TOOLS, PATH_TOOLS, VSCODE_TOOLS, VISION_TOOLS
from tools import linter, loop_guard
from tools import digest as digest_tools
from tools import vscode as vscode_tools
from tools.filesystem import project_outline
from tools.stack import stack_summary, detect_tags
from tools.cache import cache_overview, clear_cache, format_overview, human_size
from skills_loader import load_skills_for_stack
from mcp_integration import MCPManager, load_mcp_servers
from plugins_loader import PluginLoadResult, load_plugins

# --- Snapshot (автоснапшоты перед правкой) ---
try:
    from tools import snapshot
    from tools.snapshot import snapshot_file
    HAS_SNAPSHOT = True
except ImportError:
    HAS_SNAPSHOT = False
    snapshot = None
    snapshot_file = None


# ---------- UI-хелперы ----------

_TAG_RE = re.compile(r"\[/?[a-zA-Z0-9_# .]+\]")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text)


def ui_print(text: str, style: str = "") -> None:
    if console:
        if style == "markdown":
            console.print(Markdown(text))
        elif style:
            # Text, а не markup-строка: в тексте модели/ошибки могут быть
            # квадратные скобки ([...]) — их нельзя разбирать как разметку.
            console.print(Text(text, style=style))
        else:
            console.print(text)
    else:
        print(_strip_tags(text))


def ui_info(text: str) -> None:
    ui_print(f"· {text}", style="dim")


def ui_error(text: str) -> None:
    ui_print(f"[!] {text}", style="bold red")


def ui_tool_call(name: str, args: dict) -> None:
    args_preview = ", ".join(
        f"{k}={str(v)[:60]}{'...' if len(str(v)) > 60 else ''}"
        for k, v in args.items()
    )
    ui_print(f"→ {name}({args_preview})", style="cyan")


def ui_tool_result(name: str, result: str) -> None:
    preview = result.strip().splitlines()[0] if result.strip() else "(пусто)"
    if len(preview) > 100:
        preview = preview[:100] + "..."
    ui_print(f"  ✓ {preview}", style="dim green")


def fmt_num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def ui_status(status_line: str) -> None:
    """Строка статуса (контекст/токены): разметка + приглушённый стиль.

    Раньше строка печаталась как `Text(...)`, а этот класс не разбирает
    Rich-разметку — в терминал попадали литералы `[green]░…[/green]` и
    `[bold]сессия:[/bold]`. Поэтому разметку разбираем явно.
    """
    if not console:
        print(_strip_tags(status_line))
        return
    try:
        console.print(Text.from_markup(status_line, style="dim"))
    except MarkupError:
        # Чужая/некорректная разметка не должна ломать вывод статуса.
        console.print(Text(_strip_tags(status_line), style="dim"))


def _ask(prompt: str) -> str:
    """Безопасный input(): при отсутствии stdin (пайп, CI) возвращает пустую строку."""
    try:
        return input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


# ---------- Глобальные переменные ----------

# Клиент создаётся лениво (в _get_client): на момент импорта модуля ключ может
# быть ещё не задан, а падать нужно понятным сообщением, а не traceback'ом
# из openai.OpenAI().
client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Возвращает клиента OpenAI, создавая его при первом обращении."""
    global client
    if client is None:
        if not app_config.API_KEY:
            env_name = app_config.API.get("api_key_env") or "DEEPSEEK_API_KEY"
            ui_error(f"API-ключ не задан: установите {env_name} "
                     f"или api.api_key в .agent.config.json.")
            sys.exit(1)
        client = OpenAI(api_key=app_config.API_KEY,
                        base_url=app_config.BASE_URL)
    return client


# Корень проекта = папка запуска (cwd), если не переопределён в agent.config.json
# или флагом -p. Финализируется в main_async() через config.setup().
PROJECT_ROOT = Path(app_config.PROJECT_ROOT)
CONFIRM_MODE = True

# Мягкий режим планирования. Состояния:
#   auto     — по умолчанию: агент сам решает, спрашивает «планировать или сразу?»;
#   planning — только план: правки файлов запрещены, кроме PLAN.md;
#   run      — план утверждён (:plan approve): автопилот без подтверждений;
#   off      — без планирования: выполнять сразу.
PLAN_MODE = "auto"
PLAN_FILE = "PLAN.md"
CONFIRM_BEFORE_PLAN = True

DANGEROUS_TOOLS = {
    "write_file", "edit_file", "run_shell",
    "filesystem__write_file", "filesystem__edit_file",
    "filesystem__move_file", "filesystem__create_directory",
}
SNAPSHOT_TOOLS = {
    "write_file", "edit_file",
    "filesystem__write_file", "filesystem__edit_file",
}
# Инструменты, которые меняют файлы: в режиме планирования запрещены,
# кроме записи самого PLAN.md (run_shell оставлен — им план только исследуют).
WRITE_TOOLS = {
    "write_file", "edit_file",
    "filesystem__write_file", "filesystem__edit_file",
    "filesystem__move_file", "filesystem__create_directory",
}
mcp_manager: MCPManager | None = None
# Итог загрузки плагинов (см. _load_plugins): подключённые имена, инструменты,
# ошибки. Заполняется на старте, чтобы `--doctor` и баннер показали результат.
PLUGINS: PluginLoadResult | None = None

# Статистика за сессию
TOKEN_STATS = {
    "prompt": 0,
    "completion": 0,
    "total": 0,
    "cache_hit": 0,
    "cache_miss": 0,
    "reasoning": 0,
    "requests": 0,
}

CONTEXT_SIZE = 0

# Спрашивать ли при старте REPL про очистку кэша (снимается флагом --no-cache-ask).
ASK_CACHE_ON_START = True

# Сколько символов результата инструмента уходит в контекст.
TOOL_RESULT_LIMIT = 8000


# ---------- Вспомогательные функции ----------

def _nfc_casefold(text: str) -> str:
    """Ключ сравнения имён файлов: Unicode-NFC + нижний регистр."""
    return unicodedata.normalize("NFC", text).casefold()


def _match_existing(path: Path, root: Path) -> Path:
    """Возвращает фактический путь на диске (или исходный, если совпадений нет).

    Разные файловые системы обращаются с именами по-разному: macOS хранит их
    в NFD (а не в NFC, как присылает модель), Linux различает регистр, Windows
    и macOS — нет. Без этой поправки файл «src/Файл.py» из ответа модели
    молча не находился: `Path.is_file()` давал False.

    Сопоставление идёт по компонентам от корня проекта: точное совпадение
    выигрывает, иначе берётся первое имя, равное по NFC-форме без учёта
    регистра. Несуществующий хвост (например, новый файл для write_file)
    сохраняется как есть — писать его нужно в реальную папку.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        return path

    parts = list(rel.parts)
    current = root
    for i, part in enumerate(parts):
        candidate = current / part
        if candidate.exists():
            current = candidate
            continue
        try:
            entries = list(current.iterdir())
        except OSError:
            break
        key = _nfc_casefold(part)
        match = next((e for e in entries if _nfc_casefold(e.name) == key), None)
        if match is None:
            return current.joinpath(*parts[i:])
        current = match
    return current


def safe_path(path: str) -> Path:
    """Путь внутри проекта; выход за его пределы — ошибка.

    Если точного пути нет, пробуем найти фактический (`_match_existing`):
    на macOS имена файлов в NFD, а на Windows/macOS ещё и регистр не важен —
    так путь из ответа модели всё равно попадает в нужный файл.
    """
    root = PROJECT_ROOT.resolve()
    p = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if p != root and not p.is_relative_to(root):
        raise ValueError(f"Путь вне проекта запрещён: {path}")
    if not p.exists():
        p = _match_existing(p, root)
    return p


def confirm(tool_name: str, args: dict) -> bool:
    global CONFIRM_MODE
    if not CONFIRM_MODE:
        return True

    if console:
        body = "\n".join(
            f"[yellow]{k}[/yellow]: {str(v)[:300]}" for k, v in args.items()
        )
        console.print()
        console.print(Panel(body, title=f"[bold red]{tool_name}[/bold red]",
                            border_style="red"))
    else:
        print(f"\n[!] {tool_name}")
        for k, v in args.items():
            print(f"    {k}: {str(v)[:300]}")

    try:
        ans = input("Выполнить? (y/n/a=all): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if ans == "a":
        CONFIRM_MODE = False
        return True
    return ans == "y"


def plan_progress() -> tuple[int, int]:
    """Сколько задач плана отмечено сделанными и сколько их всего (по чекбоксам)."""
    path = PROJECT_ROOT / PLAN_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return (0, 0)
    done = len(re.findall(r"^\s*[-*]\s*\[[xX]\]", text, re.MULTILINE))
    total = done + len(re.findall(r"^\s*[-*]\s*\[ \]", text, re.MULTILINE))
    return (done, total)


def _is_plan_file(args: dict) -> bool:
    """Относится ли правка к самому файлу плана."""
    path = args.get("path") or ""
    return Path(str(path)).name.lower() == PLAN_FILE.lower()


def plan_guard(name: str, args: dict) -> str:
    """Запрет правок до утверждения плана. Возвращает текст отказа или "".

    Мягкий вариант: в режиме планирования менять можно только PLAN.md,
    остальное — после :plan approve (тогда включается автопилот).
    """
    if PLAN_MODE != "planning" or name not in WRITE_TOOLS or _is_plan_file(args):
        return ""
    return (
        f"ERROR: режим планирования — правки файлов запрещены до утверждения "
        f"плана ({PLAN_FILE} можно писать всегда). Составь план и попроси "
        f"подтверждение: пользователь вводит :plan approve."
    )


def make_snapshot(tool_name: str, args: dict) -> None:
    """Делает снапшот файла перед правкой. Молча пропускает ошибки."""
    if not HAS_SNAPSHOT:
        return
    if tool_name not in SNAPSHOT_TOOLS:
        return
    path = args.get("path")
    if not path:
        return
    try:
        result = snapshot_file(path)
        if result:
            ui_info(str(result))
    except Exception as e:
        ui_info(f"snapshot пропущен ({type(e).__name__}): {e}")


def _as_text_list(value) -> list[str]:
    """Строка/список → список непустых строк (для профилей и инструкций)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v) for v in value if str(v).strip()]


def project_skills_map() -> dict[str, str]:
    """Навыки проекта + навыки самого агента, объединённые по имени.

    Папки берутся из config.skills_candidates: сначала проект, затем AGENT_HOME.
    При совпадении имени навыка выигрывает проектный.

    Два режима:
      * профиль (agent.profile / --profile / :profile) — грузятся только
        перечисленные в нём навыки: агент работает «как PHP-разработчик»
        или «как Python-разработчик» независимо от содержимого проекта;
      * авто (профиль не задан) — навыки с полем `applies_to` подключаются,
        только если их тема совпадает со стеком проекта (composer.json,
        package.json, ...). Так в проект на Python не попадут правила по PHP.

    Возвращает {имя навыка: текст навыка}. Список имён показывает старт сессии.
    """
    profile = app_config.active_profile()

    tags: set[str] = set()
    only: set[str] | None = None
    if profile:
        only = set(profile.get("skills") or [])
    else:
        try:
            tags = detect_tags(PROJECT_ROOT)
        except Exception:
            tags = set()

    merged: dict[str, str] = {}
    for path in skills_candidates(PROJECT_ROOT):
        for name, content in load_skills_for_stack(str(path), tags, only=only).items():
            merged.setdefault(name, content)
    return merged


def load_project_skills() -> str:
    """Навыки для системного промпта (см. project_skills_map)."""
    return "\n\n".join(
        f"### Skill: {name}\n{content}"
        for name, content in project_skills_map().items()
    )


def _lint_has_python() -> bool:
    """Есть ли среди правил автолинта проверка Python-файлов (.py)."""
    for rule in config_lint_settings().get("rules") or []:
        exts = rule.get("ext") or []
        if isinstance(exts, str):
            exts = [exts]
        if any(str(e).lower() == ".py" for e in exts):
            return True
    return False


def _tool_examples() -> str:
    """Примеры команд проверки — генерируются из правил автолинта.

    Никаких зашитых «php -l» в тексте промпта: если в проекте проверяется,
    скажем, только Python, PHP-пример и не появится. Python-правила показаны
    с реальным интерпретатором этой ОС: команды `python` на macOS/Linux может
    не быть, а `py` есть только на Windows.
    """
    lines: list[str] = []
    for rule in config_lint_settings().get("rules") or []:
        command = linter.manual_command(rule)
        if not command:
            continue
        quote = "'" if '"' in command else '"'
        lines.append(f"  run_shell({quote}{command} путь/к/файлу{quote})")
    return "\n".join(lines) if lines else "  (правила автолинта не заданы)"


def _shell_hint() -> str:
    """Что модели нужно знать про оболочку run_shell на этой ОС.

    Без подсказки модель пишет команды «средней» ОС (`export`, `;`, `ls`),
    и на Windows они просто не выполняются — выглядит как сбой агента.
    """
    if os.name == "nt":
        return (
            "Оболочка run_shell здесь — cmd.exe (Windows), поэтому:\n"
            "- переменные: `set VAR=value && команда` — в одной команде; между\n"
            "  вызовами run_shell окружение не сохраняется, команды `export` нет;\n"
            "- разделители команд: `&&` или `&` (точка с запятой `;` не работает);\n"
            "- кавычки — двойные (`cd /d \"C:\\путь с пробелами\"`);\n"
            "- POSIX-утилит (ls, rm, sed, grep, cat, which) может не быть:\n"
            "  используй `dir`, `del`, `type`, `where`;\n"
            "- для ПОИСКА по проекту терминал не нужен: бери встроенные\n"
            "  grep/search_code/find_files — они не зависят от кодовой страницы\n"
            "  консоли. `findstr` на UTF-8 файлах с русским текстом молча даёт\n"
            "  пустой результат, поэтому для кириллицы его не используй\n"
            "  (годятся `git grep` и `python -c ...`)."
        )
    return (
        "Оболочка run_shell здесь — /bin/sh (Linux/macOS), поэтому:\n"
        "- переменные: `VAR=value команда` или `export VAR=value`; между\n"
        "  вызовами run_shell окружение не сохраняется;\n"
        "- разделители команд: `;` или `&&`, кавычки — одинарные и двойные;\n"
        "- пути — через `/`."
    )


def build_system_prompt() -> str:
    """Собирает системный промпт.

    Промпт нейтрален к языку и ОС: стек проекта определяется автоматически,
    а предметные правила живут в навыках (skills) и agent.instructions.
    """
    skills = load_project_skills()
    language = config_agent_language()

    try:
        tree = project_outline(PROJECT_ROOT, depth=2)
    except Exception:
        tree = "(не удалось получить структуру проекта)"

    try:
        stack = stack_summary(PROJECT_ROOT)
    except Exception:
        stack = "не определён"

    mcp_info = ""
    if mcp_manager and mcp_manager.get_tools():
        names = ", ".join(sorted(mcp_manager.server_names()))
        mcp_info = f"\nТакже подключены MCP-серверы: {names}."

    snapshot_info = ""
    if HAS_SNAPSHOT:
        snapshot_info = (
            f"\nПеред каждой правкой файла (write_file, edit_file) "
            f"автоматически создаётся снапшот в {backup_dir(PROJECT_ROOT)}. "
            "Откатить правку — команда :restore."
        )

    web_info = ""
    if config_web_settings().get("enabled", True):
        web_info = (
            "\n- искать в интернете (web_search) и читать страницы (fetch_url) — "
            "для проверки версий, синтаксиса библиотек и сообщений об ошибках;"
        )

    vscode_info = ""
    if vscode_tools.available():
        vscode_info = (
            "\n- открывать и закрывать файлы в редакторе VS Code "
            "(vscode_open, vscode_close, vscode_diff) — пользователь видит "
            "в отдельных вкладках, с какими файлами ты работаешь;"
        )

    vision_info = ""
    if config_vision_settings().get("enabled", True):
        vision_info = (
            "\n- смотреть изображения и скриншоты (read_image): модель "
            "мультимодальная — по картинке можно разобрать UI, график или "
            "текст со скриншота; read_file для картинок бесполезен;"
        )

    thinking_info = ""
    if config_thinking_enabled():
        thinking_info = (
            "\n- режим рассуждений включён "
            f"(усилие: {config_reasoning_effort()}): сложные задачи решай "
            "вдумчиво, простые — коротко. Переключение: :think off / :think max."
        )
    else:
        thinking_info = (
            "\n- режим рассуждений выключен: отвечай сразу, без долгих "
            "размышлений. Включить: :think on."
        )

    lint_info = ""
    lint_hints = ""
    if linter.lint_enabled():
        rules = linter.describe_rules()
        lint_info = (
            "\nПосле каждой правки файла автолинт сам проверяет синтаксис — "
            "учитывай его результат и исправь ошибку, если проверка не прошла."
        )
        if rules:
            lint_hints = (
                "\n\nНастроенные проверки (автолинт, запускаются автоматически):\n"
                + "\n".join(rules)
                + "\nТе же команды можно вызвать вручную, подставив путь:\n"
                + _tool_examples()
            )

    extra = config_agent_instructions()
    extra_block = f"\n\nДополнительные правила проекта:\n{extra}" if extra else ""

    if PLAN_MODE == "planning":
        plan_state = (
            "\nТекущий режим: ПЛАНИРОВАНИЕ. Правки других файлов заблокированы "
            f"(писать можно только {PLAN_FILE}) — исследуй код, составь план и "
            "жди подтверждения: :plan approve."
        )
    elif PLAN_MODE == "run":
        done, total = plan_progress()
        progress = f" Выполнено {done} из {total}." if total else ""
        plan_state = (
            "\nТекущий режим: АВТОПИЛОТ. План утверждён, подтверждения выключены — "
            "иди по шагам плана без остановок и вопросов по мелочам, отмечай "
            "прогресс в PLAN.md (`- [x] ID`), в конце дай короткое резюме."
            f"{progress}"
        )
    elif PLAN_MODE == "off":
        plan_state = (
            "\nТекущий режим: Планирование выключено — выполняй задачи сразу, "
            f"{PLAN_FILE} не заводи (:plan auto — вернуть решение агенту)."
        )
    else:
        plan_state = (
            "\nТекущий режим: АВТО (по умолчанию). Мелкую задачу (одна-две правки, "
            "ясная цель) выполняй сразу, без плана. Если задача крупная "
            "(несколько файлов или шагов, цель размыта) — задай один короткий "
            "вопрос в конце ответа: «Планировать (сначала план в PLAN.md) или "
            "выполнить сразу?» — и действуй по ответу: выбрали план — составь "
            "PLAN.md и жди :plan approve; выбрали «сразу» — выполняй."
        )

    plan_block = f"""
Планирование (мягкий режим):
- Мелкую задачу (одна правка, ясная цель) выполняй сразу, без плана.
- Нетривиальную задачу (несколько файлов, неясная цель) начинай с плана:
  1) если цель размыта — задай только те вопросы, что меняют структуру плана;
  2) составь план и сохрани его в {PLAN_FILE}: у задачи ID и depends_on (от
     каких задач зависит), наблюдаемое поведение (какой командой проверяется и
     что видно в выводе) и критерий приёмки; если в проекте есть тесты, шаг
     «написать/обновить тесты» идёт ДО реализации;
  3) дождись ОДНОГО подтверждения — пользователь вводит :plan approve;
  4) после подтверждения — автопилот: выполняй задачи по порядку depends_on,
     без остановок и повторных подтверждений, отмечая шаги в {PLAN_FILE}
     (`- [x] ID`). После каждого шага — линтер и узкие тесты, при падении
     исправляй; в конце — широкие тесты (pytest) и короткое резюме.
- Не переизобретай архитектуру и не расширяй план на ходу; при прерывании
  продолжай по плану.
- Команды пользователя: :plan on — план обязателен, :plan approve — утвердить,
  :plan off — без плана, :plan auto — решать самому (по умолчанию).{plan_state}
"""

    # Подсказка про интерпретатор нужна только там, где вообще есть Python.
    python_info = ""
    if _lint_has_python() or "python" in stack.lower():
        python_info = f"\n\n{app_config.python_hint()}"

    profile = app_config.active_profile()
    profile_info = ""
    profile_block = ""
    if profile:
        skills_list = ", ".join(profile["skills"]) or "—"
        profile_info = (
            f"\nПрофиль: {profile['description']} (навыки: {skills_list})."
        )
        profile_block = (
            f"\n\nАктивный профиль: {profile['description']} ({profile['name']}).\n"
            "Работай в рамках этого профиля: стек, стиль и проверки — его, даже "
            "если в проекте есть файлы других языков."
        )
        if profile["instructions"]:
            profile_block += "\n" + "\n".join(
                f"- {line}" for line in profile["instructions"]
            )

    if os.name == "nt":
        local_check_hint = (
            '  run_shell(\'powershell -Command "Test-NetConnection '
            '127.0.0.1 -Port 8124"\')'
        )
    else:
        local_check_hint = (
            '  run_shell("nc -z 127.0.0.1 8124")  '
            '# или: run_shell("curl -s http://127.0.0.1:8124")'
        )

    shell_hint = _shell_hint()

    out_limit = int(config_output_settings().get("max_chars") or 6000)
    economy_block = f"""
Экономия контекста (локальная обработка вместо простыней):
- Инструменты возвращают выжимку: бюджет ~{out_limit} символов на результат.
  Большие выводы (pytest, сборка, git log, веб-страница) сохраняются в
  .agent-cache/output/ — читай их точечно:
  read_range("путь", start, end) или search_code(шаблон, ".agent-cache/output", "*").
- Не читай файл целиком, чтобы найти одну функцию: file_outline(path) — карта
  символов, затем read_symbol("имя", path) или read_range(...).
- Не вываливай дерево проекта: find_files("**/*.py") или project_map(depth=2).
- Сравнивай файлы через diff_files(a, b) — только изменения, без двух простыней.
- Веб: fetch_url(url, query="ключевые слова") отдаёт абзацы по теме, а не всю страницу.
- Shell-команды делай «тихими»: pytest -q, git log -5, git diff --stat,
  git status --short, grep с -m/--include — тогда ответ умещается целиком.
"""

    return f"""Ты CLI-агент для написания и правки кода.
Ты работаешь с проектом в директории: {PROJECT_ROOT}
Система: {platform.system()} {platform.release()}
Настройки и все пути задаются в одном редактируемом файле: {CONFIG_PATH}
(команда :config показывает текущие значения).
Определённый стек проекта: {stack}{profile_info}

Структура проекта (до 2 уровней; полный список — list_dir):
{tree}

Твои возможности:
- читать, писать и точечно редактировать файлы;
- искать по коду: grep (регулярки), search_code (сводка по файлам с контекстом),
  file_outline (карта символов), read_symbol (тело функции по имени);
- сравнивать файлы (diff_files), искать файлы по маске (find_files),
  смотреть структуру проекта (project_map);
- запускать shell-команды (тесты, сборка, линтеры);
- смотреть состояние репозитория: git_status, git_diff, git_log;{web_info}{vscode_info}{vision_info}{thinking_info}
- использовать инструменты MCP-серверов, если они подключены;
- следовать правилам навыков (skills), описанных ниже.
{mcp_info}{snapshot_info}{lint_info}{python_info}

Как решать типовые задачи:

- Перед правкой файла всегда сначала прочитай его (read_file / read_range).
- Небольшая правка существующего кода — edit_file; новый файл или полная
  перезапись — write_file.
- Переименовать/заменить во всех местах файла:
  edit_file(path=..., old_text=..., new_text=..., replace_all=true)
- Найти использования класса или функции:
  search_code("имя_функции", ".", include=".php")  # сводка вместо простыни
- Понять устройство файла: file_outline("путь") — классы/функции с номерами
  строк, затем read_symbol("имя", "путь") или read_range("путь", 400, 600).
- Большой файл целиком не читается (обрезается) — используй
  read_range("путь", 400, 600).
- Понять, что уже изменено: git_status(), затем git_diff(path="src/File.php"),
  либо diff_files("файл", "снапшот") для двух версий.{lint_hints}
{economy_block}{plan_block}

Правила:
- Отвечай кратко, на {language}.
- Меняй только то, что нужно для задачи: минимальный диф, без массового
  переформатирования чужих участков.
- Не оставляй отладочный код (var_dump, print_r, console.log, print, dd) в правках.
- Все пути — относительно корня проекта, без ведущего слэша.
- Когда задача выполнена — дай короткое резюме изменений.

Оболочка:
{shell_hint}{extra_block}

Правила для фоновых процессов:
- НЕ запускай долгоживущие серверы (php -S, node server.js, python -m http.server)
  через run_shell — команда не завершится, и агент зависнет.
- Если нужно проверить работу локального сервера, попроси пользователя запустить
  его в отдельном терминале, а сам делай короткую проверку одной командой,
  которая завершается сама:
  run_shell("curl -s http://127.0.0.1:8124")
{local_check_hint}

Навыки проекта:
{skills or "(навыки не найдены)"}{profile_block}
"""


# ---------- Плагины (доп. инструменты из plugins/) ----------

def _load_plugins() -> None:
    """Подключает плагины: инструменты из папок `paths.plugins_dirs`.

    Папки ищутся по цепочке «проект → папка агента» (config.plugins_candidates),
    каждый плагин — .py-файл с `register(api)` (см. plugins_loader.py).
    Ошибки плагинов печатаются, но старт агента не прерывают.
    """
    global PLUGINS
    try:
        PLUGINS = load_plugins(reserved=set(REGISTRY))
    except Exception as e:  # noqa: BLE001 — плагины не должны ронять старт
        PLUGINS = None
        ui_error(f"плагины: {type(e).__name__}: {e}")
        return

    if PLUGINS.tools:
        TOOLS.extend(PLUGINS.tools)
        REGISTRY.update(PLUGINS.handlers)
        # Опасные инструменты плагина ведут себя как write_file: подтверждение
        # и блокировка в режиме планирования.
        DANGEROUS_TOOLS.update(PLUGINS.dangerous)
        WRITE_TOOLS.update(PLUGINS.dangerous)

    for error in PLUGINS.errors:
        ui_error(f"плагин: {error}")


# ---------- Сборка списка инструментов с дедупликацией ----------

def build_tools_list() -> list[dict]:
    """Объединяет встроенные инструменты и MCP-инструменты,
    убирая дубликаты по имени (приоритет — встроенным).

    Инструменты, которые сейчас неприменимы (веб выключен в конфиге,
    проект не под git), не отдаются модели, чтобы не тратить контекст.
    """
    all_tools = list(TOOLS)
    if mcp_manager:
        all_tools += mcp_manager.get_tools()

    web_on = bool(config_web_settings().get("enabled", True))
    git_on = (PROJECT_ROOT / ".git").exists()
    vscode_on = vscode_tools.available()
    vision_on = bool(config_vision_settings().get("enabled", True))

    seen: set[str] = set()
    deduped: list[dict] = []
    for tool in all_tools:
        name = (tool.get("function") or {}).get("name")
        if not name:
            continue
        if name in seen:
            continue
        if not web_on and name in WEB_TOOLS:
            continue
        if not git_on and name in GIT_TOOLS:
            continue
        if not vscode_on and name in VSCODE_TOOLS:
            continue
        if not vision_on and name in VISION_TOOLS:
            continue
        seen.add(name)
        deduped.append(tool)
    return deduped


# ---------- Лог сессии (для отладки) ----------

LOG_PATH: Path | None = None


def _open_session_log() -> None:
    """Открывает файл лога сессии в <project>/.agent-cache/logs/."""
    global LOG_PATH
    try:
        logs = cache_dir(PROJECT_ROOT) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        LOG_PATH = logs / f"session-{datetime.now():%Y-%m-%d-%H%M%S}.log"
        log_line("session", f"agent.py start, project={PROJECT_ROOT}, "
                            f"model={app_config.MODEL}")
    except OSError:
        LOG_PATH = None


def log_line(kind: str, text: str) -> None:
    """Пишет строку в лог сессии (ошибки логирования игнорируются)."""
    if not LOG_PATH:
        return
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {kind}: {text}\n")
    except OSError:
        pass


# ---------- Выполнение инструментов ----------

# Правки, после которых файл автоматически показывается в VS Code.
VSCODE_EDIT_TOOLS = {
    "write_file", "edit_file",
    "filesystem__write_file", "filesystem__edit_file",
}


def _auto_open_in_vscode(name: str, args: dict, result: str) -> str:
    """Открывает правленый файл в VS Code — видно, как агент работает.

    Работает, только если запущено расширение-мост (vscode-extension/) и
    vscode.auto_open не выключен. Ошибки открытия молча игнорируются, чтобы
    интеграция не мешала основной работе.
    """
    if name not in VSCODE_EDIT_TOOLS:
        return result
    if not result or result.startswith("ERROR"):
        return result
    path = args.get("path")
    if not path:
        return result
    try:
        note = vscode_tools.auto_open(str(path))
    except Exception:  # noqa: BLE001 — автооткрытие не должно ронять инструмент
        note = ""
    if note:
        log_line("vscode", note)
    return f"{result}\n{note}" if note else result


async def execute_tool(name: str, args: dict) -> str | list[dict]:
    """Выполняет инструмент.

    Обычно возвращает текст результата; инструменты с изображениями (read_image)
    возвращают список контент-блоков — их кладёт в диалог _run_loop.
    """
    # ---- Встроенные инструменты ----
    if name in REGISTRY:
        # Для инструментов с путями по умолчанию считаем от корня проекта,
        # а не от cwd процесса: иначе "." зависел бы от того, откуда запущен агент.
        if name in PATH_TOOLS:
            args.setdefault("path", str(PROJECT_ROOT))
        if "path" in args:
            try:
                args["path"] = str(safe_path(args["path"]))
            except ValueError as e:
                return f"ERROR: {e}"
        # Сравнение файлов: оба аргумента — пути внутри проекта.
        for key in ("path_a", "path_b"):
            if args.get(key):
                try:
                    args[key] = str(safe_path(args[key]))
                except ValueError as e:
                    return f"ERROR: {e}"

        # Автоснапшот перед правкой
        if name in SNAPSHOT_TOOLS:
            make_snapshot(name, args)

        # Мягкое планирование: до утверждения плана меняем только PLAN.md.
        blocked = plan_guard(name, args)
        if blocked:
            return blocked

        # Подтверждение для опасных операций
        if name in DANGEROUS_TOOLS and not confirm(name, args):
            return "Пользователь отклонил выполнение."

        try:
            result = REGISTRY[name](**args)
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

        # Контент-блоки (read_image): текст, линт и автооткрытие к ним неприменимы.
        if isinstance(result, list):
            return result

        result = str(result)

        # Единый бюджет вывода: большой результат превращается в выжимку,
        # полный текст сохраняется в .agent-cache/output (tools/digest.py).
        result = digest_tools.compress_result(name, result, args)
        # Автолинт: после правки файла сразу проверяем синтаксис.
        result = linter.lint_result(name, args, result)
        # Автооткрытие правленого файла в VS Code (если запущено расширение-мост).
        return _auto_open_in_vscode(name, args, result)

    # ---- MCP-инструменты ----
    if mcp_manager and mcp_manager.has_tool(name):
        # Снапшоты работают и для MCP-правок (filesystem__write_file и т.п.).
        if name in SNAPSHOT_TOOLS and args.get("path"):
            make_snapshot(name, args)
        # Мягкое планирование: до утверждения плана меняем только PLAN.md.
        blocked = plan_guard(name, args)
        if blocked:
            return blocked
        if name in DANGEROUS_TOOLS and not confirm(name, args):
            return "Пользователь отклонил выполнение."
        mcp_result = await mcp_manager.call_tool(name, args)
        # MCP-выводы (чтение файлов, списки, деревья) тоже укладываем в бюджет.
        mcp_result = digest_tools.compress_result(name, str(mcp_result), args)
        return _auto_open_in_vscode(name, args, mcp_result)

    return f"ERROR: неизвестный инструмент {name}"


# ---------- Вызов модели ----------

def _update_stats(usage) -> None:
    global CONTEXT_SIZE
    if not usage:
        return
    p = getattr(usage, "prompt_tokens", 0) or 0
    c = getattr(usage, "completion_tokens", 0) or 0
    t = getattr(usage, "total_tokens", 0) or 0
    ch = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
    cm = getattr(usage, "prompt_cache_miss_tokens", 0) or 0
    details = getattr(usage, "completion_tokens_details", None)
    rt = (getattr(details, "reasoning_tokens", 0) or 0) if details else 0

    TOKEN_STATS["prompt"] += p
    TOKEN_STATS["completion"] += c
    TOKEN_STATS["total"] += t
    TOKEN_STATS["cache_hit"] += ch
    TOKEN_STATS["cache_miss"] += cm
    TOKEN_STATS["reasoning"] += rt
    TOKEN_STATS["requests"] += 1

    CONTEXT_SIZE = p


def _context_bar() -> str:
    # Лимит читается из настроек (app_config): если проект задан флагом -p,
    # config.setup() перечитывает конфиг, а константы импорта остаются старыми.
    limit = app_config.CONTEXT_LIMIT or 0
    if limit <= 0:
        return f"контекст: {fmt_num(CONTEXT_SIZE)} токенов"
    pct = min(100, int(CONTEXT_SIZE * 100 / limit))
    # Дробные проценты не должны выглядеть как «пустой» бар: при 4%
    # int(4/5) давало 0 закрашенных блоков — показываем хотя бы один.
    filled = min(20, int(round(pct * 20 / 100)))
    if pct > 0 and filled == 0:
        filled = 1
    bar = "█" * filled + "░" * (20 - filled)
    color = "green"
    if pct > 80:
        color = "red"
    elif pct > 60:
        color = "yellow"
    return (
        f"контекст: [{color}]{bar}[/{color}] "
        f"{fmt_num(CONTEXT_SIZE)}/{fmt_num(limit)} ({pct}%)"
    )


def _session_stats() -> str:
    """Основная строка статистики: без кэша и рассуждений (они — во второй)."""
    s = TOKEN_STATS
    if s["requests"] == 0:
        return "токенов пока не потрачено"
    return (
        f"[bold]сессия:[/bold] {s['requests']} зап. | "
        f"prompt: {fmt_num(s['prompt'])} | "
        f"completion: {fmt_num(s['completion'])} | "
        f"total: {fmt_num(s['total'])}"
    )


def _cache_stats() -> str:
    """Вторая строка статуса: кэш промпта и токены рассуждений.

    Раньше всё было одной строкой ~110 символов, и терминал переносил
    её посреди значения («… / 23 881» + «miss»).
    """
    s = TOKEN_STATS
    parts: list[str] = []
    if s["cache_hit"] or s["cache_miss"]:
        parts.append(f"cache: {fmt_num(s['cache_hit'])} hit"
                     f" / {fmt_num(s['cache_miss'])} miss")
    if s.get("reasoning"):
        parts.append(f"рассуждения: {fmt_num(s['reasoning'])}")
    return " | ".join(parts)


def print_stats(full: bool = False) -> None:
    ui_status(_context_bar())
    if full:
        s = TOKEN_STATS
        ui_print(f"""[bold]Статистика сессии[/bold]
  запросов:   {s['requests']}
  prompt:     {fmt_num(s['prompt'])}
  completion: {fmt_num(s['completion'])}
  рассужд.:   {fmt_num(s['reasoning'])}
  total:      {fmt_num(s['total'])}
  cache hit:  {fmt_num(s['cache_hit'])}
  cache miss: {fmt_num(s['cache_miss'])}""")
        return
    ui_status(_session_stats())
    extra = _cache_stats()
    if extra:
        ui_status(extra)


def _thinking_extra_body() -> dict:
    """Параметры thinking mode для тела запроса.

    `thinking` и `reasoning_effort` не входят в типизированный набор SDK,
    поэтому передаём их через extra_body — так работает на любой версии
    openai>=1.40 (см. https://api-docs.deepseek.com/guides/thinking_mode).
    """
    body: dict = {
        "thinking": {"type": "enabled" if config_thinking_enabled() else "disabled"}
    }
    if config_thinking_enabled():
        body["reasoning_effort"] = config_reasoning_effort()
    return body


def _request_kwargs(messages: list, all_tools: list) -> dict:
    """Аргументы chat.completions.create с учётом настроек проекта.

    temperature в thinking mode не действует (так и описано в API), поэтому
    при включённых рассуждениях она просто уходит «в никуда» — это не ошибка.
    tool_choice="auto": значения required и named в thinking mode запрещены
    (API отвечает 400).
    """
    kwargs: dict = {
        "model": app_config.MODEL,
        "messages": messages,
        "tools": all_tools,
        "tool_choice": "auto",
        "temperature": app_config.TEMPERATURE,
        "extra_body": _thinking_extra_body(),
    }
    max_tokens = config_max_output_tokens()
    if max_tokens > 0:
        kwargs["max_tokens"] = max_tokens
    top_p = config_api_top_p()
    if top_p:
        kwargs["top_p"] = min(1.0, max(0.01, top_p))
    return kwargs


def _api_request(messages: list, all_tools: list):
    """Один (блокирующий) запрос к API. Со спиннером, если есть rich.

    model/temperature берутся из app_config, а не из констант, загруженных при
    импорте: если корень проекта задан флагом -p, config.setup() перечитывает
    конфиг, и запрос должен уйти с настройками именно этого проекта.
    Режим задаёт api.stream: стриминг (текст печатается по ходу генерации)
    или ожидание ответа целиком.
    """
    if config_stream_enabled():
        return _stream_request(messages, all_tools)

    kwargs = _request_kwargs(messages, all_tools)
    if console:
        spinner = Spinner("dots", text=Text(" DeepSeek думает...", style="dim"))
        with Live(spinner, console=console, refresh_per_second=10, transient=True):
            return _get_client().chat.completions.create(**kwargs)
    print("... DeepSeek думает", end="", flush=True)
    try:
        return _get_client().chat.completions.create(**kwargs)
    finally:
        print("\r", end="")


def _stream_write(text: str, style: str = "") -> None:
    """Печатает кусок стриминга без перевода строки."""
    if console:
        renderable = Text(text, style=style) if style else text
        console.print(renderable, end="", highlight=False, markup=bool(style),
                      soft_wrap=True)
    else:
        sys.stdout.write(text)
        sys.stdout.flush()


def _clear_stream_hint() -> None:
    """Стирает строку-подсказку «DeepSeek думает» перед первым токеном."""
    print("\r" + " " * 24 + "\r", end="", flush=True)


def _stream_request(messages: list, all_tools: list):
    """Стриминговый запрос (stream=true): печатает ответ по мере генерации.

    Возвращает объект того же вида, что и нестримовый ответ SDK
    (choices[0].message + usage), только собранный из чанков, — поэтому
    `_run_loop` разбирает оба режима одинаково. Накопленные tool_calls
    склеиваются по index: имя приходит в первом чанке, аргументы — кусками.
    """
    kwargs = _request_kwargs(messages, all_tools)
    kwargs["stream"] = True
    kwargs["stream_options"] = {"include_usage": True}

    content: list[str] = []
    reasoning: list[str] = []
    calls: dict[int, dict] = {}
    finish: str | None = None
    usage = None
    hint = True
    answering = False

    print("... DeepSeek думает", end="", flush=True)
    try:
        for chunk in _get_client().chat.completions.create(**kwargs):
            if hint:
                _clear_stream_hint()
                hint = False
            usage = getattr(chunk, "usage", None) or usage
            for choice in getattr(chunk, "choices", None) or []:
                if getattr(choice, "finish_reason", None):
                    finish = choice.finish_reason
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                thought = getattr(delta, "reasoning_content", None)
                if thought:
                    if not reasoning:
                        _stream_write("💭 ", style="dim italic")
                    reasoning.append(thought)
                    _stream_write(thought, style="dim italic")

                text = getattr(delta, "content", None)
                if text:
                    if reasoning and not answering:
                        _stream_write("\n")
                    content.append(text)
                    answering = True
                    _stream_write(text)

                for call in getattr(delta, "tool_calls", None) or []:
                    index = int(getattr(call, "index", 0) or 0)
                    slot = calls.setdefault(index, {"id": "", "name": "", "args": []})
                    if getattr(call, "id", None):
                        slot["id"] = call.id
                    function = getattr(call, "function", None)
                    if function is not None:
                        if getattr(function, "name", None):
                            slot["name"] = function.name
                        if getattr(function, "arguments", None):
                            slot["args"].append(function.arguments)
    finally:
        if hint:
            _clear_stream_hint()

    message = SimpleNamespace(
        content="".join(content) or None,
        reasoning_content="".join(reasoning) or None,
        tool_calls=[
            SimpleNamespace(
                id=slot["id"] or f"call_{index}",
                type="function",
                function=SimpleNamespace(
                    name=slot["name"],
                    arguments="".join(slot["args"]) or "{}",
                ),
            )
            for index, slot in sorted(calls.items())
        ],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=usage,
        streamed=True,
    )


def _assistant_message(msg) -> dict:
    """Сообщение ассистента для истории диалога (dict, а не объект SDK).

    История уходит обратно в API и считается в :context, поэтому приводим её
    к JSON-совместимому виду — независимо от того, пришёл ответ стримингом
    (SimpleNamespace) или целиком (pydantic-объект SDK).
    """
    history: dict = {"role": "assistant", "content": msg.content or ""}
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        history["reasoning_content"] = reasoning
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        history["tool_calls"] = [
            {
                "id": call.id,
                "type": getattr(call, "type", None) or "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for call in tool_calls
        ]
    return history


async def _call_model(messages: list, all_tools: list):
    """Запрос к DeepSeek с повторами при сетевых ошибках/429.

    Количество попыток — agent.api_retries. Задержка растёт: 1с, 2с, 4с...
    """
    attempts = max(1, config_api_retries())
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return _api_request(messages, all_tools)
        except Exception as e:
            last_error = e
            if attempt == attempts or not _is_retryable(e):
                break
            delay = 2 ** (attempt - 1)
            ui_info(f"API-сбой ({type(e).__name__}), повтор "
                    f"{attempt}/{attempts - 1} через {delay} с")
            await asyncio.sleep(delay)

    ui_error(f"API: {type(last_error).__name__}: {last_error}")
    log_line("api-error", f"{type(last_error).__name__}: {last_error}")
    return None


def _is_retryable(error: Exception) -> bool:
    """Стоит ли повторять запрос: сетевые ошибки, 429 и 5xx."""
    status = getattr(error, "status_code", None)
    if status in (408, 409, 429):
        return True
    if isinstance(status, int) and 500 <= status < 600:
        return True
    name = type(error).__name__
    return name in {
        "APIConnectionError", "APITimeoutError", "RateLimitError",
        "InternalServerError", "Timeout", "ConnectTimeout",
    }


async def _run_loop(messages: list) -> None:
    all_tools = build_tools_list()
    # max_steps <= 0 => без ограничений (см. config.max_steps): от зацикливания
    # защищает loop-guard, см. tools/loop_guard.py.
    max_steps = config_max_steps()
    guard = loop_guard.LoopGuard()
    step = 0

    while True:
        step += 1
        if max_steps > 0 and step > max_steps:
            ui_error(
                f"Достигнут лимит шагов ({max_steps}) — останавливаюсь. "
                "Уточните задачу или уберите лимит: agent.max_steps = 0 "
                "в agent.config.json (0 = без ограничений, зацикливание ловит "
                "agent.loop_guard)."
            )
            log_line("limit", f"max_steps={max_steps} reached")
            return

        response = await _call_model(messages, all_tools)
        if response is None:
            return

        _update_stats(getattr(response, "usage", None))

        choice = response.choices[0]
        msg = choice.message
        finish = getattr(choice, "finish_reason", None)
        if finish == "length":
            ui_info("ответ обрезан по лимиту токенов (finish_reason=length) — "
                    "увеличь api.max_tokens или разбей задачу на части")
            log_line("api", "finish_reason=length")
        elif finish in ("insufficient_system_resource", "aborted"):
            ui_info(f"генерация прервана на стороне API "
                    f"(finish_reason={finish}) — ответ может быть неполным")
            log_line("api", f"finish_reason={finish}")

        reasoning = getattr(msg, "reasoning_content", None)
        # При стриминге рассуждения и текст уже напечатаны по ходу генерации.
        streamed = bool(getattr(response, "streamed", False))
        if reasoning and not streamed:
            ui_print(f"💭 {reasoning}", style="dim italic")

        if not msg.tool_calls:
            print()
            if streamed:
                if not msg.content:
                    ui_print("(пустой ответ)")
            else:
                ui_print(msg.content or "(пустой ответ)", style="markdown")
            log_line("assistant", (msg.content or "")[:1000].replace("\n", " "))
            print()
            print_stats()
            print()
            return

        messages.append(_assistant_message(msg))
        if streamed and (reasoning or msg.content):
            print()                     # отделяем напечатанный текст от вызовов

        warned: list[str] = []
        image_parts: list[dict] = []      # изображения — отдельным user-сообщением
        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            ui_tool_call(name, args)
            log_line("tool", f"{name}({json.dumps(args, ensure_ascii=False)[:500]})")

            result = await execute_tool(name, args)
            if isinstance(result, list):
                # Инструмент вернул контент-блоки (read_image): текст идёт в
                # tool-сообщение, картинки — в user-сообщение ниже.
                blocks = result
                text = " ".join(
                    str(b.get("text") or "") for b in blocks
                    if isinstance(b, dict) and b.get("type") == "text"
                ).strip()
                image_parts.extend(
                    b for b in blocks
                    if isinstance(b, dict) and b.get("type") != "text"
                )
                result = text or "[изображение передано модели]"

            ui_tool_result(name, result)
            log_line("result", str(result)[:1000].replace("\n", " "))

            # Последний предохранитель: если инструмент вернул больше бюджета,
            # модель получает выжимку, а полный текст — в .agent-cache/output.
            content = digest_tools.compress_result(name, str(result), args)
            if len(content) > TOOL_RESULT_LIMIT:
                content = content[:TOOL_RESULT_LIMIT] + (
                    f"\n\n[... результат обрезан: показано {TOOL_RESULT_LIMIT} "
                    f"из {len(content)} символов. Сузь запрос.]")

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": content,
            })

            # Зацикливание: одинаковый вызов с тем же результатом подряд.
            state = guard.observe(name, args, str(result))
            if state == loop_guard.STOP:
                print()
                ui_error(guard.message(name, args))
                log_line("loop-guard", f"stop: {loop_guard.describe_call(name, args)}")
                print()
                return
            if state == loop_guard.WARN:
                warned.append(guard.warning(name, args))
                log_line("loop-guard", f"warn: {loop_guard.describe_call(name, args)}")

        # Предупреждения добавляем после результатов инструментов, чтобы не
        # разрывать пары assistant(tool_calls) → tool.
        for text in warned:
            messages.append({"role": "user", "content": text})
            ui_info("Похоже на цикл: прошу модель сменить подход.")

        # Изображения из read_image: по документации DeepSeek они допустимы
        # только в user-сообщениях (в system/assistant API отвечает 400),
        # поэтому идут отдельным сообщением после всех tool-ответов.
        if image_parts:
            messages.append({
                "role": "user",
                "content": [{"type": "text",
                             "text": "Изображения из read_image (приложены к запросу):"},
                            *image_parts],
            })
            log_line("vision", f"{len(image_parts)} image part(s) sent")


# ---------- Команды REPL ----------

def cmd_help() -> None:
    ui_print("""[bold]Команды:[/bold]
  [cyan]:help[/cyan]              — эта справка
  [cyan]:clear[/cyan]             — очистить историю диалога
  [cyan]:tokens[/cyan]            — статистика токенов за сессию
  [cyan]:context[/cyan]           — размер текущего контекста
  [cyan]:tools[/cyan]             — доступные инструменты (вкл. web, git, vscode)
  [cyan]:lint [файл][/cyan]      — прогнать автолинт (php -l / node --check / ...)
  [cyan]:profile [имя][/cyan]    — показать/сменить профиль (php, python, ...)
  [cyan]:profiles[/cyan]         — список профилей (ролей) агента
  [cyan]:think [режим][/cyan]    — thinking mode: on/off, усилие low/high/max, auto
  [cyan]:stream [on|off][/cyan]  — стриминг ответа; по умолчанию off (спиннер + markdown)
  [cyan]:skills[/cyan]            — загруженные навыки
  [cyan]:mcp[/cyan]               — статус MCP-серверов
  [cyan]:vscode[/cyan]            — статус моста к VS Code; [cyan]:vscode start[/cyan] — поднять редактор
  [cyan]:snapshots[/cyan]         — список снапшотов
  [cyan]:restore[/cyan]           — восстановить последний снапшот
  [cyan]:auto[/cyan]              — переключить режим подтверждений
  [cyan]:plan [on|approve|off|auto][/cyan] — планирование: план в PLAN.md → автопилот
  [cyan]:project[/cyan]           — показать корень проекта
  [cyan]:cache[/cyan]             — объём кэша (.agent-cache) и очистка
  [cyan]:log[/cyan]               — путь к логу текущей сессии
  [cyan]:doctor[/cyan]            — диагностика (config, skills, mcp, утилиты)
  [cyan]:config[/cyan]            — путь к agent.config.json и текущие настройки
  [cyan]:exit[/cyan] или exit     — выход
""")


def cmd_log() -> None:
    if LOG_PATH:
        ui_info(f"Лог сессии: {LOG_PATH}")
    else:
        ui_info("Лог сессии недоступен (не удалось создать файл).")


def cmd_cache(force: bool = False) -> None:
    """Показывает объём кэша и (после подтверждения) чистит его.

    Кэш — это `.agent-cache` в проекте: снапшоты правок, логи сессий и
    история ввода. Чистка ускоряет grep/read_file и не даёт мусору
    попадать в контекст модели.
    """
    info = cache_overview(PROJECT_ROOT)
    ui_print("[bold]Кэш агента[/bold]")
    for line in format_overview(info).splitlines():
        ui_print(f"  {line}")
    if info["total_items"] == 0:
        ui_info("Кэш пуст — очищать нечего.")
        return

    if not force:
        ans = _ask("Очистить кэш (снапшоты, логи, история ввода)? (y/n): ")
        if ans != "y":
            ui_info("Оставлено без изменений.")
            return

    ui_print(clear_cache(PROJECT_ROOT), style="green")
    ui_info("Учтите: откат :restore для удалённых снапшотов больше недоступен.")


def maybe_ask_cache_clear() -> None:
    """Спрашивает при старте REPL, стоит ли очистить кэш.

    Отключается флагом --no-cache-ask или ключом cache.ask_on_start в конфиге.
    """
    if not config_ask_cache_on_start():
        return
    info = cache_overview(PROJECT_ROOT)
    if info["total_items"] == 0:
        return

    ui_print(
        f"[bold]Кэш проекта[/bold]: снапшотов {info['backups']['count']}, "
        f"логов {info['logs']['count']}, "
        f"история ввода — {'есть' if info['history']['count'] else 'нет'} "
        f"(всего {human_size(info['total_bytes'])})",
        style="dim",
    )
    ans = _ask("Очистить кэш перед началом работы? "
               "[Enter] — оставить, y — очистить: ")
    if ans == "y":
        ui_print(clear_cache(PROJECT_ROOT), style="green")
    else:
        ui_info("Кэш оставлен. Очистить в любой момент — команда :cache.")


def cmd_tokens() -> None:
    if TOKEN_STATS["requests"] == 0:
        ui_info("Пока не было запросов к API.")
        return
    print_stats(full=True)


def cmd_context() -> None:
    ui_print(_context_bar())
    limit = app_config.CONTEXT_LIMIT or 0
    if limit > 0:
        left = max(0, limit - CONTEXT_SIZE)
        ui_info(f"Свободно в контексте: {fmt_num(left)} токенов")
        if CONTEXT_SIZE > limit * 0.8:
            ui_print("[yellow]Контекст почти заполнен. "
                     "Рекомендую :clear и начать новую задачу.[/yellow]")


def cmd_tools() -> None:
    """Показывает список инструментов, которые реально получает модель."""
    all_tools = build_tools_list()
    builtin: list[str] = []
    mcp: list[str] = []
    for tool in all_tools:
        name = (tool.get("function") or {}).get("name", "?")
        if "__" in name:
            mcp.append(name)
        else:
            builtin.append(name)

    ui_print(f"[bold]Встроенные ({len(builtin)}):[/bold]")
    for n in sorted(builtin):
        ui_print(f"  · {n}", style="cyan")

    if mcp:
        ui_print(f"[bold]MCP ({len(mcp)}):[/bold]")
        for n in sorted(mcp):
            ui_print(f"  · {n}", style="magenta")


def cmd_lint(arg: str = "") -> None:
    """Ручной запуск автолинта для одного файла (:lint путь/к/файлу)."""
    raw = (arg or "").strip()
    if not raw:
        ui_error("Использование: :lint путь/к/файлу")
        rules = linter.describe_rules()
        if rules:
            ui_info("Настроенные проверки:")
            for line in rules:
                ui_print(f"  {line}", style="dim")
        else:
            ui_info("Правила автолинта не заданы (секция lint в agent.config.json).")
        return

    target = Path(raw) if Path(raw).is_absolute() else PROJECT_ROOT / raw
    report = linter.lint_file(target)
    if report is None:
        ui_info("Для этого файла нет правила автолинта "
                "(проверь расширение и секцию lint в agent.config.json).")
        return
    ui_print(report, style="green" if report.endswith("OK") else "yellow")


def cmd_skills() -> None:
    profile = app_config.active_profile()
    if profile:
        ui_info(f"Профиль: {profile['name']} — {profile['description']} "
                f"(навыки: {', '.join(profile['skills']) or '—'})")
    skills = load_project_skills()
    if not skills:
        ui_info("Навыки не найдены.")
        if profile:
            ui_info("Проверьте имена навыков в профиле и папку skills/.")
        return
    for line in skills.splitlines():
        if line.startswith("### Skill:"):
            ui_print(f"· {line.replace('### Skill:', '').strip()}", style="cyan")


def cmd_profiles() -> None:
    """Список профилей (ролей) агента с описанием."""
    all_profiles = app_config.profiles()
    current = app_config.active_profile()
    requested = app_config.agent_profile()
    if not all_profiles:
        ui_info("Профили не заданы (секция profiles в agent.config.json).")
        return
    ui_print("[bold]Профили:[/bold]")
    for name in sorted(all_profiles):
        cfg = all_profiles[name]
        mark = "→" if current and current["name"] == name else " "
        skills = ", ".join(_as_text_list(cfg.get("skills"))) or "—"
        ui_print(f" {mark} [cyan]{name}[/cyan] — {cfg.get('description') or ''}")
        ui_print(f"     навыки: {skills}", style="dim")
    if requested and not current:
        ui_error(f"Профиль «{requested}» не найден — работаю автоматически по стеку.")
    ui_info("Переключение: :profile <имя>, :profile auto (авто по стеку), "
            "флаг --profile <имя>.")


def cmd_profile(arg: str = "") -> bool:
    """Показать активный профиль или переключить его (:profile php).

    Возвращает True, если профиль изменён (нужно пересобрать системный промпт).
    """
    name = (arg or "").strip()
    if name.lower() in ("list", "all"):
        cmd_profiles()
        return False
    if not name:
        current = app_config.active_profile()
        requested = app_config.agent_profile()
        if current:
            ui_info(f"Активный профиль: {current['name']} — {current['description']}")
            ui_info(f"Навыки: {', '.join(current['skills']) or '—'}")
        elif requested:
            ui_error(f"Профиль «{requested}» не найден в секции profiles.")
        else:
            ui_info("Профиль не задан — навыки выбираются по стеку проекта.")
        cmd_profiles()
        return False

    if name.lower() in ("auto", "none", "off", "-"):
        app_config.set_profile("")
        ui_info("Профиль сброшен: навыки снова выбираются по стеку проекта.")
        return True

    if name.lower() not in app_config.profiles():
        ui_error(f"Неизвестный профиль: {name}")
        cmd_profiles()
        return False

    app_config.set_profile(name.lower())
    current = app_config.active_profile()
    ui_info(f"Профиль: {current['name']} — {current['description']}")
    ui_info(f"Навыки: {', '.join(current['skills']) or '—'}")
    return True


def cmd_think(arg: str = "") -> bool:
    """Показать/сменить thinking mode: :think on|off|low|high|max|auto.

    Возвращает True, если настройки изменены (нужен новый системный промпт).
    """
    arg = (arg or "").strip().lower()
    if not arg or arg in ("status", "info"):
        max_tokens = config_max_output_tokens()
        ui_info(f"thinking: {config_thinking_summary()}  ·  "
                f"temperature: {app_config.TEMPERATURE}  ·  "
                f"max_tokens: {max_tokens or 'по умолчанию API'}")
        if config_thinking_enabled():
            ui_info("В thinking mode temperature не действует, top_p "
                    "у deepseek-flash работает в диапазоне 0.95–1.0.")
        else:
            ui_info("Без рассуждений действует temperature, ответы короче и дешевле.")
        ui_info("Переключение: :think on | off | low | high | max | auto")
        return False

    if arg in ("auto", "reset", "default", "-"):
        config_set_thinking(None)
        config_set_reasoning_effort(None)
        ui_info(f"thinking: {config_thinking_summary()} (из конфига)")
        return True

    if arg in ("on", "off", "enable", "disable", "true", "false"):
        enabled = config_set_thinking(
            "low" if arg in ("on", "enable", "true") else "none"
        )
        ui_info(f"thinking: {'вкл' if enabled else 'выкл'} "
                f"(усилие: {config_reasoning_effort()})")
        return True

    if arg in ("none", "low", "high", "max", "minimal", "medium", "xhigh", "ultra"):
        effort = config_set_reasoning_effort(arg)
        ui_info(f"thinking: {'вкл' if config_thinking_enabled() else 'выкл'} "
                f"(усилие: {effort})")
        return True

    ui_error("Использование: :think  |  :think on/off  |  :think low|high|max  |  "
             ":think auto")
    return False


def cmd_stream(arg: str = "") -> bool:
    """Показать/сменить стриминг ответа: :stream on|off|auto."""
    arg = (arg or "").strip().lower()
    if not arg or arg in ("status", "info"):
        ui_info(f"stream: {config_stream_summary()}")
        ui_info("Переключение: :stream on | off | auto (значение из конфига)")
        return False

    if arg in ("auto", "reset", "default", "-"):
        config_set_stream(None)
    elif arg in ("on", "off", "enable", "disable", "true", "false", "yes", "no"):
        config_set_stream(arg)
    else:
        ui_error("Использование: :stream  |  :stream on/off  |  :stream auto")
        return False

    ui_info(f"stream: {config_stream_summary()}")
    return True


def _refresh_system_prompt(messages: list) -> None:
    """Пересобирает системный промпт в истории диалога (смена профиля, :think)."""
    if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        messages[0]["content"] = build_system_prompt()
        ui_info("Системный промпт обновлён (настройки перечитаны).")


def cmd_mcp() -> None:
    if not mcp_manager or not mcp_manager.get_tools():
        ui_info("MCP-серверы не подключены.")
        return
    servers: dict[str, list[str]] = {}
    for tool_name, info in mcp_manager._tool_map.items():
        srv = info["server"]
        servers.setdefault(srv, []).append(tool_name)
    for srv, tools in servers.items():
        ui_print(f"{srv}: {len(tools)} инструментов", style="bold cyan")


def _start_vscode_bridge() -> None:
    """Поднимает мост к VS Code на старте: при необходимости запускает редактор.

    Вызывается только в интерактивном режиме (см. main_async) и никогда не
    мешает работе: если CLI `code` или расширения нет — просто печатает подсказку.
    """
    settings = app_config.vscode_settings()
    if not settings.get("enabled", True):
        return

    info = vscode_tools.bridge_info(PROJECT_ROOT)
    if info and vscode_tools.available(force=True):
        ui_info(f"VS Code: мост активен (127.0.0.1:{info.get('port')})")
        return
    if not settings.get("auto_start", True):
        ui_info("VS Code: мост не активен — поднять: :vscode start")
        return

    status = vscode_tools.bootstrap(PROJECT_ROOT)
    if vscode_tools.available(force=True):
        ui_print(f"[green]✓[/green] VS Code: {status}")
    else:
        ui_print(f"[yellow]~[/yellow] VS Code: {status}")


def cmd_vscode(arg: str = "") -> None:
    """Статус моста к VS Code; `:vscode start` — запустить редактор и мост."""
    settings = app_config.vscode_settings()
    if not settings.get("enabled", True):
        ui_info("Интеграция с VS Code выключена (vscode.enabled = false).")
        return

    arg = (arg or "").strip().lower()
    if arg in ("start", "restart", "on"):
        ui_info("VS Code: запускаю редактор с проектом…")
        status = vscode_tools.bootstrap(PROJECT_ROOT, force=(arg == "restart"))
        if vscode_tools.available(force=True):
            ui_print(f"[green]✓[/green] VS Code: {status}")
        else:
            ui_print(f"[yellow]~[/yellow] VS Code: {status}")
        return
    if arg and arg not in ("status", "info"):
        ui_error("Использование: :vscode  или  :vscode start")
        return

    info = vscode_tools.bridge_info(PROJECT_ROOT)
    if not info:
        ui_error("Мост к VS Code не найден — расширение не запущено.")
        ui_info("Установите расширение из папки vscode-extension/ "
                "(см. vscode-extension/README.md) и откройте проект в VS Code.")
        ui_info("Либо просто введите :vscode start — агент запустит редактор сам.")
        ui_info(f"Ожидается файл: {vscode_tools.bridge_file(PROJECT_ROOT)}")
        return

    if not vscode_tools.available(force=True):
        ui_error("Файл моста есть, но VS Code не отвечает — похоже, редактор "
                 "был закрыт аварийно.")
        ui_info("Перезапустите мост: :vscode restart (агент сам откроет VS Code).")
        ui_info("Либо перезапустите VS Code вручную: расширение пересоздаст "
                f"{vscode_tools.bridge_file(PROJECT_ROOT).name}.")
        return

    ui_print(f"[green]✓[/green] мост активен: 127.0.0.1:{info.get('port')}")
    ui_print(f"    проект:  {info.get('workspace')}", style="dim")
    ui_info(f"авто-открытие правок: "
            f"{'вкл' if settings.get('auto_open', True) else 'выкл'}")


def cmd_snapshots() -> None:
    """Показывает список снапшотов (каталог — из agent.config.json)."""
    backup = backup_dir(PROJECT_ROOT)
    if not backup.is_dir():
        ui_info(f"Снапшотов нет ({backup}).")
        return
    items = sorted(backup.iterdir(), key=lambda p: p.name, reverse=True)
    if not items:
        ui_info("Снапшотов нет.")
        return
    ui_print(f"[bold]Снапшоты[/bold] ({len(items)} шт.): {backup}")
    for item in items[:20]:
        kind = "dir" if item.is_dir() else "zip"
        size = 0
        if item.is_file():
            size = item.stat().st_size
        ui_print(f"  · {item.name}  [{kind}]"
                 + (f"  {fmt_num(size)} байт" if size else ""),
                 style="cyan")
    if len(items) > 20:
        ui_info(f"… и ещё {len(items) - 20}")


def cmd_restore() -> None:
    """Восстанавливает файлы из последнего снапшота-папки."""
    backup = backup_dir(PROJECT_ROOT)
    if not backup.is_dir():
        ui_error("Снапшотов нет.")
        return
    snapshots = sorted(
        [p for p in backup.iterdir() if p.is_dir()],
        key=lambda p: p.name, reverse=True,
    )
    if not snapshots:
        ui_error("Снапшотов-папок нет (есть только zip-архивы). "
                 "Восстановите вручную из .zip.")
        return
    latest = snapshots[0]
    files = [f for f in latest.rglob("*") if f.is_file()]
    if not files:
        ui_error(f"Снапшот {latest.name} пуст.")
        return

    ui_print(f"[bold]Последний снапшот:[/bold] {latest.name}")
    for f in files:
        rel = f.relative_to(latest)
        ui_print(f"  · {rel}", style="cyan")

    try:
        ans = input("Восстановить эти файлы? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if ans != "y":
        ui_info("Отменено.")
        return

    restored = 0
    for f in files:
        rel = f.relative_to(latest)
        target = PROJECT_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        restored += 1
    ui_print(f"[green]Восстановлено файлов: {restored}[/green]")


def cmd_auto() -> None:
    global CONFIRM_MODE
    CONFIRM_MODE = not CONFIRM_MODE
    state = "ВЫКЛ" if not CONFIRM_MODE else "ВКЛ"
    ui_info(f"Подтверждения: {state}")


def cmd_plan(arg: str = "") -> bool:
    """Показать/сменить режим планирования: :plan [on|approve|off|auto].

    auto     — по умолчанию: агент сам решает и спрашивает, если задача крупная;
    on       — только план: правки файлов запрещены, писать можно лишь PLAN.md;
    approve  — план утверждён: автопилот, подтверждения выключаются;
    off      — без планирования: задачи выполняются сразу;
    auto     — вернуть решение агенту.

    Возвращает True, если режим изменился (нужен новый системный промпт).
    """
    global PLAN_MODE, CONFIRM_MODE, CONFIRM_BEFORE_PLAN
    arg = (arg or "").strip().lower()

    if not arg or arg in ("status", "info"):
        done, total = plan_progress()
        progress = f", шагов выполнено {done} из {total}" if total else ""
        ui_info(f"планирование: {PLAN_MODE}{progress}  ·  "
                f"план: {PROJECT_ROOT / PLAN_FILE}  ·  "
                f"подтверждения: {'вкл' if CONFIRM_MODE else 'выкл'}")
        ui_info("Переключение: :plan on | approve | off | auto")
        return False

    if arg in ("on", "plan", "planning"):
        PLAN_MODE = "planning"
        ui_info(f"Планирование ВКЛ: правки файлов заблокированы, писать можно "
                f"только {PLAN_FILE}. Утвердить план — :plan approve.")
        return True

    if arg in ("approve", "ok", "go", "yes", "да", "run"):
        done, total = plan_progress()
        if not total:
            ui_info(f"{PLAN_FILE} пока пуст или без чекбоксов — план будет "
                    "выполняться по описанию из ответа.")
        CONFIRM_BEFORE_PLAN = CONFIRM_MODE
        PLAN_MODE = "run"
        CONFIRM_MODE = False
        ui_info(f"План утверждён: автопилот, подтверждения выключены "
                f"({done}/{total} шагов). Завершить — :plan off.")
        return True

    if arg in ("off", "stop", "done", "exit", "auto", "default"):
        was_run = PLAN_MODE == "run"
        PLAN_MODE = "auto" if arg in ("auto", "default") else "off"
        if was_run:
            CONFIRM_MODE = CONFIRM_BEFORE_PLAN
        ui_info(f"Планирование: {PLAN_MODE}, подтверждения: "
                f"{'вкл' if CONFIRM_MODE else 'выкл'}.")
        return True

    ui_error("Использование: :plan  |  :plan on  |  :plan approve  |  "
             ":plan off  |  :plan auto")
    return False


def cmd_doctor() -> None:
    ui_print("[bold]Диагностика агента[/bold]\n")
    ui_print(f"[cyan]AGENT_HOME:[/cyan]   {agent_home()}")
    ui_print(f"[cyan]agent.py:[/cyan]     {Path(__file__).resolve()}")
    ui_print(f"[cyan]PROJECT_ROOT:[/cyan] {PROJECT_ROOT}")
    ui_print(f"[cyan]cwd:[/cyan]          {Path.cwd()}")
    try:
        ui_print(f"[cyan]стек:[/cyan]         {stack_summary(PROJECT_ROOT)}")
    except Exception:
        pass
    print()

    ui_print("[bold]Автолинт[/bold]")
    if linter.lint_enabled():
        for line in linter.describe_rules() or ["  (правил нет)"]:
            ui_print(f"  {line}", style="dim")
    else:
        ui_print("  ~ выключен (секция lint в agent.config.json)", style="yellow")
    print()

    ui_print("[bold]Профиль (роль)[/bold]")
    profile = app_config.active_profile()
    requested = app_config.agent_profile()
    if profile:
        ui_print(f"  ✓ {profile['name']} — {profile['description']}")
        ui_print(f"      навыки: {', '.join(profile['skills']) or '—'}", style="dim")
    elif requested:
        ui_print(f"  ✗ профиль «{requested}» не найден — работаю авто по стеку",
                 style="yellow")
    else:
        ui_print("  ~ не задан — навыки выбираются автоматически по стеку проекта",
                 style="dim")
    all_profiles = sorted(app_config.profiles())
    if all_profiles:
        ui_print(f"      доступны: {', '.join(all_profiles)}", style="dim")
    print()

    ui_print("[bold]Конфиги[/bold]")
    if app_config.LOADED_CONFIGS:
        for conf in app_config.LOADED_CONFIGS:
            ui_print(f"  ✓ {conf}")
    else:
        ui_print("  ~ файлов конфигурации нет, работают значения по умолчанию",
                 style="yellow")
    for line in settings_summary().splitlines():
        ui_print(f"      {line}", style="dim")
    print()

    ui_print("[bold]Skills[/bold]")
    candidates = skills_candidates(PROJECT_ROOT)
    found_any = False
    for path in candidates:
        if path.is_dir():
            skill_files = list(path.rglob("SKILL.md"))
            if skill_files:
                found_any = True
                ui_print(f"  ✓ {path}  ({len(skill_files)} навыков)")
                for sf in skill_files:
                    ui_print(f"      · {sf.parent.name}", style="dim")
            else:
                ui_print(f"  ~ {path}  (папка есть, но SKILL.md не найдено)",
                         style="yellow")
        else:
            ui_print(f"  ✗ {path}  (нет папки)", style="dim")
    if not found_any:
        ui_print("  → создайте skills/<name>/SKILL.md в проекте или рядом с агентом",
                 style="yellow")
    print()

    ui_print("[bold]MCP[/bold]")
    mcp_paths = mcp_config_paths(PROJECT_ROOT)
    if mcp_paths:
        for path in mcp_paths:
            ui_print(f"  ✓ конфиг: {path}")
    else:
        raw_mcp = app_config.PATHS.get("mcp_config") or "mcp_config.json"
        for name in (raw_mcp if isinstance(raw_mcp, list) else [raw_mcp]):
            ui_print(f"  ✗ {name} (нет ни в проекте, ни в папке агента)", style="dim")
        ui_print("  → создайте mcp_config.json в проекте или рядом с агентом",
                 style="yellow")

    if mcp_manager and mcp_manager.get_tools():
        servers: dict[str, list[str]] = {}
        for tool_name, info in mcp_manager._tool_map.items():
            srv = info["server"]
            servers.setdefault(srv, []).append(tool_name)
        for srv, tools in servers.items():
            ui_print(f"  ✓ сервер {srv}: {len(tools)} инструментов")
    elif mcp_paths:
        ui_print("  ~ конфиг есть, но ни один сервер не подключён", style="yellow")
    print()

    ui_print("[bold]VS Code[/bold]")
    vscode_cfg = app_config.vscode_settings()
    if not vscode_cfg.get("enabled", True):
        ui_print("  ~ интеграция выключена (vscode.enabled = false)", style="yellow")
    else:
        vscode_bridge = vscode_tools.bridge_info(PROJECT_ROOT)
        if vscode_bridge and vscode_tools.available(force=True):
            ui_print(f"  ✓ мост активен: 127.0.0.1:{vscode_bridge.get('port')}")
            ui_print(f"      проект: {vscode_bridge.get('workspace')}", style="dim")
            ui_print(f"      авто-открытие правок: "
                     f"{'вкл' if vscode_cfg.get('auto_open', True) else 'выкл'}",
                     style="dim")
        elif vscode_bridge:
            ui_print("  ~ файл моста есть, но VS Code не отвечает "
                     "(закрыт аварийно?)", style="yellow")
            ui_print("      → перезапустите VS Code", style="yellow")
        else:
            ui_print("  ✗ мост не найден (расширение vscode-extension/)", style="dim")
            ui_print(f"      ожидается {vscode_tools.bridge_file(PROJECT_ROOT)}",
                     style="dim")
            ui_print("      → установите расширение: vscode-extension/README.md",
                     style="yellow")
            if vscode_cfg.get("auto_start", True):
                ui_print("      → автозапуск включён (vscode.auto_start): в "
                         "интерактивном режиме агент откроет VS Code сам",
                         style="dim")
            else:
                ui_print("      → автозапуск выключен: введите :vscode start",
                         style="dim")
    print()

    ui_print("[bold]Снапшоты[/bold]")
    if HAS_SNAPSHOT:
        backup = backup_dir(PROJECT_ROOT)
        if backup.is_dir():
            n = len(list(backup.iterdir()))
            ui_print(f"  ✓ модуль подключён, снапшотов: {n}  ({backup})")
        else:
            ui_print(f"  ~ модуль подключён, снапшотов пока нет  ({backup})")
    else:
        ui_print("  ✗ tools/snapshot.py не найден", style="red")
    cache_info = cache_overview(PROJECT_ROOT)
    ui_print(f"  кэш: {cache_info['total_items']} файлов, "
             f"{human_size(cache_info['total_bytes'])}  ({cache_info['dir']})")
    ui_print("  очистка: :cache, :cache clear или флаг --clear-cache", style="dim")
    print()

    ui_print("[bold]Плагины[/bold]")
    dirs = plugins_candidates(PROJECT_ROOT)
    if dirs:
        for path in dirs:
            ui_print(f"  ✓ папка: {path}")
    else:
        ui_print("  ~ папок plugins/ нет (ключ paths.plugins_dirs)", style="dim")
    if PLUGINS and PLUGINS.loaded:
        ui_print(f"  ✓ подключено плагинов: {len(PLUGINS.loaded)} — "
                 f"{', '.join(PLUGINS.loaded)}")
        ui_print(f"  инструментов от плагинов: {len(PLUGINS.handlers)}")
    elif dirs:
        ui_print("  ~ плагинов не найдено (файлы *.py с функцией register(api))",
                 style="dim")
    for error in (PLUGINS.errors if PLUGINS else []):
        ui_print(f"  ✗ {error}", style="red")
    print()

    ui_print("[bold]Утилиты[/bold]")
    for name in ("git", "npx", "node", "uvx", "php", "python", "python3", "py",
                 "javac", "kotlinc", "swiftc"):
        found = shutil.which(name)
        mark = "✓" if found else "✗"
        color = "green" if found else "dim"
        ui_print(f"  [{color}]{mark}[/{color}] {name}" +
                 (f"  {found}" if found else ""))
    ui_print(f"  интерпретатор агента: {app_config.python_exe()}")
    print()

    ui_print("[bold]Пакеты Python[/bold]")
    import importlib.util

    # pytest — не рантайм-зависимость, а инструмент разработки (requirements-dev.txt).
    for module, required, hint in (
        ("openai", True, "pip install -r requirements.txt"),
        ("mcp", True, "pip install -r requirements.txt"),
        ("rich", False, ""),
        ("prompt_toolkit", False, ""),
        ("pytest", False, "pip install -r requirements-dev.txt"),
    ):
        found = importlib.util.find_spec(module) is not None
        if found:
            ui_print(f"  [green]✓[/green] {module}")
        elif required:
            ui_print(f"  [red]✗ {module} — обязателен. "
                     f"Установите: {hint}[/red]")
        elif hint:
            ui_print(f"  [yellow]~[/yellow] {module} — не установлен "
                     f"(нужен для тестов: {hint})")
        else:
            ui_print(f"  [yellow]~[/yellow] {module} — не установлен "
                     "(необязателен, будет упрощённый режим)")
    ui_print("  установка в текущий интерпретатор: "
             f"{app_config.python_command('-m', 'pip', 'install', '-r', 'requirements-dev.txt')}",
             style="dim")
    print()

    ui_print("[bold]API-ключ[/bold]")
    env_name = app_config.API.get("api_key_env") or "DEEPSEEK_API_KEY"
    if app_config.API_KEY:
        if os.environ.get(env_name):
            source = "из переменной окружения"
        elif app_config.env_value(env_name):
            source = "из реестра Windows (переменная окружения)"
        else:
            source = "из .agent.config.json"
        ui_print(f"  [green]✓[/green] задан ({source}, {env_name})")
    else:
        ui_print("  [red]✗ не найден[/red] — задайте DEEPSEEK_API_KEY "
                 "или api.api_key в .agent.config.json")
    ui_print(f"  модель: {app_config.MODEL}   base_url: {app_config.BASE_URL}")


def cmd_config() -> None:
    """Показывает путь к конфигу и текущие значения."""
    ui_print(f"[bold]Файл настроек:[/bold] {CONFIG_PATH}"
             + ("" if CONFIG_PATH.is_file() else "  (не найден — используются дефолты)"))
    ui_print(settings_summary())
    ui_info("Правьте agent.config.json и перезапускайте агента — код менять не нужно.")


async def handle_command(cmd: str, messages: list) -> bool:
    c = cmd.strip().lower()
    if c == ":help":
        cmd_help()
    elif c == ":clear":
        messages.clear()
        ui_info("История очищена.")
        global CONTEXT_SIZE
        CONTEXT_SIZE = 0
    elif c == ":tokens":
        cmd_tokens()
    elif c == ":context":
        cmd_context()
    elif c == ":tools":
        cmd_tools()
    elif c == ":lint":
        cmd_lint()
    elif c.startswith(":lint "):
        cmd_lint(c.split(None, 1)[1])
    elif c == ":skills":
        cmd_skills()
    elif c == ":profile":
        cmd_profile()
    elif c.startswith(":profile "):
        if cmd_profile(c.split(None, 1)[1]):
            _refresh_system_prompt(messages)
    elif c == ":profiles":
        cmd_profiles()
    elif c == ":think":
        if cmd_think():
            _refresh_system_prompt(messages)
    elif c.startswith(":think "):
        if cmd_think(c.split(None, 1)[1]):
            _refresh_system_prompt(messages)
    elif c == ":stream":
        cmd_stream()
    elif c.startswith(":stream "):
        cmd_stream(c.split(None, 1)[1])
    elif c == ":mcp":
        cmd_mcp()
    elif c == ":vscode":
        cmd_vscode()
    elif c.startswith(":vscode "):
        cmd_vscode(c.split(None, 1)[1])
    elif c == ":snapshots":
        cmd_snapshots()
    elif c == ":restore":
        cmd_restore()
    elif c == ":auto":
        cmd_auto()
    elif c == ":plan":
        if cmd_plan():
            _refresh_system_prompt(messages)
    elif c.startswith(":plan "):
        if cmd_plan(c.split(None, 1)[1]):
            _refresh_system_prompt(messages)
    elif c == ":project":
        ui_info(f"Проект: {PROJECT_ROOT}")
    elif c == ":cache":
        cmd_cache()
    elif c.startswith(":cache "):
        # :cache clear — очистить без вопросов
        arg = c.split(None, 1)[1].strip()
        if arg in ("clear", "clean", "y", "yes"):
            cmd_cache(force=True)
        else:
            ui_error("Использование: :cache  или  :cache clear")
    elif c == ":log":
        cmd_log()
    elif c == ":doctor":
        cmd_doctor()
    elif c == ":config":
        cmd_config()
    else:
        return False
    return True


# ---------- Интерактивный режим ----------

async def repl(system_prompt: str) -> None:
    messages = [{"role": "system", "content": system_prompt}]

    session = None
    if HAS_PT:
        try:
            history_file = cache_dir(PROJECT_ROOT) / "history.txt"
            history_file.parent.mkdir(parents=True, exist_ok=True)
            session = PromptSession(history=FileHistory(str(history_file)))
        except Exception as e:
            # Нет настоящей консоли (пайп, CI, удалённый терминал) —
            # продолжаем с простым input().
            ui_info(f"prompt_toolkit недоступен ({type(e).__name__}), "
                    f"использую обычный ввод")
            session = None

    ui_print("[bold cyan]DeepSeek Agent[/bold cyan] — интерактивный режим")
    ui_info("Введите задачу или :help для списка команд. Выход — :exit или Ctrl+D.")
    if LOG_PATH:
        ui_info(f"лог сессии: {LOG_PATH}")
    print()

    if ASK_CACHE_ON_START:
        maybe_ask_cache_clear()
        print()

    while True:
        try:
            if session:
                with patch_stdout():
                    user_input = await session.prompt_async(
                        ANSI("\x1b[1;36m>>> \x1b[0m")
                    )
            else:
                user_input = input(">>> ")
        except (EOFError, KeyboardInterrupt):
            print()
            ui_info("Выход.")
            return

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", ":q", ":exit"}:
            ui_info("Выход.")
            return

        if user_input.startswith(":"):
            if await handle_command(user_input, messages):
                continue
            ui_error(f"Неизвестная команда: {user_input}. Введите :help.")
            continue

        messages.append({"role": "user", "content": user_input})
        log_line("user", user_input[:500].replace("\n", " "))
        try:
            await _run_loop(messages)
        except KeyboardInterrupt:
            print()
            ui_info("Прервано. Продолжаем сессию.")


# ---------- Точка входа ----------

async def main_async(args) -> None:
    global PROJECT_ROOT, CONFIRM_MODE, mcp_manager, ASK_CACHE_ON_START

    if args.list_profiles:
        PROJECT_ROOT = config_setup(args.project_root)
        cmd_profiles()
        return

    # Диагностика работает без API-ключа: удобно проверить установку сразу
    # после клонирования, до настройки ключа.
    if args.doctor:
        PROJECT_ROOT = config_setup(args.project_root)
        if args.profile:
            app_config.set_profile(args.profile)
        _open_session_log()
        _load_plugins()
        if args.clear_cache:
            ui_print(clear_cache(PROJECT_ROOT), style="green")
        cmd_doctor()
        return

    # Определяем корень проекта и перечитываем конфиги: -p > DEEPSEEK_PROJECT_ROOT
    # > конфиг в проекте > agent.config.json > cwd (папка запуска).
    PROJECT_ROOT = config_setup(args.project_root)
    if not PROJECT_ROOT.is_dir():
        ui_error(f"Папка не найдена: {PROJECT_ROOT}")
        sys.exit(1)

    # Ключ проверяем после config_setup(): проектный .agent.config.json тоже
    # может его задавать. Значение читаем из config, а не из импортированной копии.
    if not app_config.API_KEY:
        env_name = app_config.API.get("api_key_env") or "DEEPSEEK_API_KEY"
        ui_error(f"API-ключ не найден (ни ${env_name}, ни api.api_key в конфиге).")
        if os.name == "nt":
            print(f'  Windows (cmd):        setx {env_name} "sk-..."')
            print(f'  Windows (PowerShell): $env:{env_name} = "sk-..."')
            print('  После setx переменная видна только НОВЫМ терминалам; '
                  'агент дополнительно читает её из реестра Windows.')
        else:
            print(f'  Linux/macOS:          export {env_name}="sk-..."')
            print(f'                        (постоянно: добавьте строку '
                  f'в ~/.bashrc или ~/.zshrc и выполните `source ~/.bashrc`)')
        print(f'  Либо укажите ключ в api.api_key файла .agent.config.json.')
        sys.exit(1)

    _get_client()  # создаём клиента сразу, чтобы ошибки в конфиге были видны на старте

    # Профиль из командной строки перекрывает agent.profile на время сессии.
    if args.profile:
        app_config.set_profile(args.profile)
        if not app_config.active_profile():
            ui_error(f"Неизвестный профиль: {args.profile} "
                     f"(доступны: {', '.join(app_config.profile_names()) or 'нет'})")
            sys.exit(1)

    if HAS_SNAPSHOT:
        snapshot.set_project_root(PROJECT_ROOT)

    if args.no_confirm or args.yes:
        CONFIRM_MODE = False

    if args.no_cache_ask:
        ASK_CACHE_ON_START = False

    _open_session_log()

    # Плагины: дополнительные инструменты из plugins/ (до сборки промпта и
    # списка инструментов — иначе модель их не увидит).
    _load_plugins()

    if args.clear_cache:
        ui_print(clear_cache(PROJECT_ROOT), style="green")
        log_line("cache", "cleared by --clear-cache")

    ui_print(f"[bold]DeepSeek Agent[/bold]  ·  проект: [cyan]{PROJECT_ROOT}[/cyan]")
    ui_print(f"                ·  модель: [cyan]{app_config.MODEL}[/cyan]  "
             f"·  подтверждения: [cyan]{'выкл' if not CONFIRM_MODE else 'вкл'}[/cyan]")
    if PLAN_MODE != "auto":
        ui_info(f"планирование: {PLAN_MODE} ({PLAN_FILE})")
    ui_info(f"агент: {agent_home()}")
    try:
        ui_info(f"стек проекта: {stack_summary(PROJECT_ROOT)}  ·  "
                f"автолинт: {'вкл' if linter.lint_enabled() else 'выкл'}")
    except Exception:
        pass
    profile = app_config.active_profile()
    if profile:
        ui_info(f"профиль: {profile['name']} — {profile['description']}")
    else:
        requested = app_config.agent_profile()
        if requested:
            ui_info(f"профиль «{requested}» не найден — работаю авто по стеку")
        else:
            ui_info("профиль: авто (навыки по стеку проекта) "
                    "· сменить: --profile <имя> или :profile <имя>")
    ui_info(f"thinking mode: {config_thinking_summary()}  ·  "
            f"max_tokens: {config_max_output_tokens() or 'по умолчанию API'}  "
            "· сменить: :think")
    try:
        skill_names = list(project_skills_map())
    except Exception:
        skill_names = []
    ui_info(f"навыки ({len(skill_names)}): "
            f"{', '.join(skill_names) if skill_names else '—'}")
    log_line("profile", app_config.agent_profile() or "auto")
    for conf in app_config.LOADED_CONFIGS:
        ui_info(f"конфиг: {conf}")
    if PLUGINS and (PLUGINS.loaded or PLUGINS.errors):
        ui_info(f"плагины: {PLUGINS.summary()}")
    if HAS_SNAPSHOT:
        ui_info(f"автоснапшоты: включены ({backup_dir(PROJECT_ROOT)})")
    else:
        ui_print("[yellow]автоснапшоты: выключены — tools/snapshot.py не найден[/yellow]")

    # MCP-конфиги ищутся автоматически: сначала в проекте, затем в папке агента.
    mcp_paths = mcp_config_paths(PROJECT_ROOT)
    if mcp_paths:
        servers_by_name = {}
        for path in mcp_paths:
            try:
                for srv in await load_mcp_servers(
                    str(path), variables=config_variables(PROJECT_ROOT)
                ):
                    # Серверы из проектного конфига приоритетнее агентских.
                    servers_by_name.setdefault(srv.name, srv)
            except Exception as e:
                ui_error(f"MCP: {path}: {type(e).__name__}: {e}")

        if servers_by_name:
            mcp_manager = MCPManager()
            # Корни отдаём клиентом (roots/list), а не аргументами сервера:
            # иначе сервер пишет в stderr «Client does not support MCP Roots».
            await mcp_manager.connect(
                list(servers_by_name.values()), roots=mcp_roots(PROJECT_ROOT)
            )
            ui_info(f"MCP: {len(mcp_manager.get_tools())} инструментов "
                    f"из {len(servers_by_name)} серверов "
                    f"({', '.join(str(p) for p in mcp_paths)})")

    # Мост к VS Code: в интерактивном режиме агент сам поднимает редактор,
    # если моста нет (vscode.auto_start). Для разовых задач (-t) не вмешиваемся.
    if not args.task:
        _start_vscode_bridge()

    print()

    try:
        if args.task:
            system_prompt = build_system_prompt()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": args.task},
            ]
            log_line("user", args.task[:500].replace("\n", " "))
            await _run_loop(messages)
            if args.show_tokens:
                print()
                cmd_tokens()
        else:
            system_prompt = build_system_prompt()
            await repl(system_prompt)
    finally:
        if mcp_manager:
            await mcp_manager.close()


def main():
    parser = argparse.ArgumentParser(
        description="DeepSeek CLI Agent — помощник по коду в вашем проекте."
    )
    parser.add_argument("-p", "--project-root", default=None,
                        help="Корень проекта. По умолчанию — папка запуска (cwd), "
                             "если не задан в agent.config.json.")
    parser.add_argument("--profile", default=None, metavar="ИМЯ",
                        help="Профиль (роль) агента: php, python, frontend или "
                             "свой из секции profiles. Внутри сессии — :profile.")
    parser.add_argument("--list-profiles", action="store_true",
                        help="Показать доступные профили и выйти (API-ключ не нужен).")
    parser.add_argument("-t", "--task",
                        help="Разовая задача. Без неё — интерактивный REPL.")
    parser.add_argument("--no-confirm", action="store_true",
                        help="Отключить подтверждения.")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Алиас --no-confirm (для CI/автоматизации).")
    parser.add_argument("--show-tokens", action="store_true",
                        help="Показать статистику токенов после разовой задачи.")
    parser.add_argument("--doctor", action="store_true",
                        help="Показать диагностику (пути, конфиги, навыки, MCP, "
                             "наличие утилит) и выйти. API-ключ не нужен.")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Очистить кэш проекта (.agent-cache: снапшоты, логи, "
                             "история ввода) перед запуском, без вопросов.")
    parser.add_argument("--no-cache-ask", action="store_true",
                        help="Не спрашивать при старте про очистку кэша.")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print()
        ui_info("Прервано.")


if __name__ == "__main__":
    main()