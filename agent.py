"""
DeepSeek CLI Agent для написания PHP/Python кода.

Возможности:
- работа с конкретным проектом (--project-root);
- подтверждение опасных операций;
- автоснапшоты файлов перед правкой (.agent-cache/backups/);
- навыки (skills) из корня проекта или рядом с агентом;
- MCP-серверы через mcp_config.json;
- интерактивный REPL с командами (:help, :tokens, :context, :restore, ...);
- спиннер, цветной вывод, статистика токенов и размера контекста.
"""

import os
import re
import sys
import json
import argparse
import asyncio
import subprocess
from pathlib import Path

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
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None

# --- UI: prompt_toolkit (опционально) ---
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.patch_stdout import patch_stdout
    HAS_PT = True
except ImportError:
    HAS_PT = False

import config as app_config
from config import (
    API_KEY,
    BASE_URL,
    MODEL,
    TEMPERATURE,
    CONTEXT_LIMIT,
    CONFIG_PATH,
    agent_home,
    backup_dir,
    mcp_config_paths,
    plugins_candidates,
    skills_candidates,
    settings_summary,
    variables as config_variables,
    setup as config_setup,
)
from tools import TOOLS, REGISTRY
from skills_loader import load_skill_map
from mcp_integration import MCPManager, load_mcp_servers

# --- Snapshot (автоснапшоты перед правкой) ---
try:
    from tools import snapshot
    from tools.snapshot import snapshot_file, snapshot_dir
    HAS_SNAPSHOT = True
except ImportError:
    HAS_SNAPSHOT = False
    snapshot = None
    snapshot_file = None
    snapshot_dir = None


# ---------- UI-хелперы ----------

_TAG_RE = re.compile(r"\[/?[a-zA-Z0-9_# .]+\]")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text)


def ui_print(text: str, style: str = "") -> None:
    if console:
        if style == "markdown":
            console.print(Markdown(text))
        elif style:
            console.print(f"[{style}]{text}[/{style}]")
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
    ui_print(status_line, style="dim")


# ---------- Глобальные переменные ----------

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# Корень проекта = папка запуска (cwd), если не переопределён в agent.config.json
# или флагом -p. Финализируется в main_async() через config.setup().
PROJECT_ROOT = Path(app_config.PROJECT_ROOT)
CONFIRM_MODE = True
DANGEROUS_TOOLS = {
    "write_file", "edit_file", "run_shell",
    "filesystem__write_file", "filesystem__edit_file",
    "filesystem__move_file", "filesystem__create_directory",
}
SNAPSHOT_TOOLS = {
    "write_file", "edit_file",
    "filesystem__write_file", "filesystem__edit_file",
}
mcp_manager: MCPManager | None = None

# Статистика за сессию
TOKEN_STATS = {
    "prompt": 0,
    "completion": 0,
    "total": 0,
    "cache_hit": 0,
    "cache_miss": 0,
    "requests": 0,
}

CONTEXT_SIZE = 0
CONTEXT_LIMIT = CONTEXT_LIMIT or 0


# ---------- Вспомогательные функции ----------

def safe_path(path: str) -> Path:
    root = PROJECT_ROOT.resolve()
    p = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if p != root and not p.is_relative_to(root):
        raise ValueError(f"Путь вне проекта запрещён: {path}")
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


def load_project_skills() -> str:
    """Навыки проекта + навыки самого агента, объединённые по имени.

    Папки берутся из config.skills_candidates: сначала проект, затем AGENT_HOME.
    При совпадении имени навыка выигрывает проектный.
    """
    merged: dict[str, str] = {}
    for path in skills_candidates(PROJECT_ROOT):
        for name, content in load_skill_map(str(path)).items():
            merged.setdefault(name, content)
    return "\n\n".join(
        f"### Skill: {name}\n{content}" for name, content in merged.items()
    )


def build_system_prompt() -> str:
    """Собирает системный промпт с навыками и структурой проекта."""
    skills = load_project_skills()

    try:
        cmd = ["cmd", "/c", "dir", "/b"] if os.name == "nt" else ["ls", "-1"]
        tree = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        tree = "(не удалось получить список файлов)"

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

    return f"""Ты CLI-агент для написания PHP и Python кода на Windows.
Ты работаешь с проектом в директории: {PROJECT_ROOT}
Настройки и все пути задаются в одном редактируемом файле: {CONFIG_PATH}
(команда :config показывает текущие значения).

Верхний уровень проекта:
{tree}

Твои возможности:
- читать, писать и точечно редактировать файлы;
- искать по коду регулярными выражениями;
- запускать shell-команды (php -l, node --check, python -m pytest);
- использовать инструменты MCP-серверов, если они подключены;
- следовать правилам навыков, описанных ниже.
{mcp_info}{snapshot_info}

Как решать типовые задачи:

- Проверить синтаксис PHP после правки:
  run_shell("php -l путь/к/файлу.php")

- Проверить JS:
  run_shell("node --check путь/к/файлу.js")

- Найти все использования класса или функции:
  grep("имя_класса", ".", ".php")     # третий аргумент — расширение

- Прочитать середину большого файла (когда read_file обрезает):
  read_range("путь", 400, 600)

Правила:
- Отвечай кратко, на русском.
- Перед правкой файла сначала прочитай его.
- Для небольших правок используй `edit_file`, а не `write_file`.
- После правки PHP-файла обязательно запусти `php -l`.
- Все пути — относительно корня проекта, без ведущего слэша.
- Когда задача выполнена — дай короткое резюме изменений.

Правила для фоновых процессов:
- НЕ запускай долгоживущие серверы (php -S, node server.js, python -m http.server)
  через run_shell — команда не завершится, и агент зависнет.
- Если нужно проверить работу локального сервера:
  1. Попроси пользователя запустить сервер в отдельном терминале.
  2. Или запусти короткую проверку одной командой, которая сама завершается:
     run_shell("php -l file.php")              — проверка синтаксиса
     run_shell("curl -s http://127.0.0.1:8124")  — один запрос, ответ, выход
- Для проверки, что сервер поднимается, используй:
  run_shell("powershell -Command \"Test-NetConnection 127.0.0.1 -Port 8124\"")

Навыки проекта:
{skills or "(навыки не найдены)"}
"""


# ---------- Сборка списка инструментов с дедупликацией ----------

def build_tools_list() -> list[dict]:
    """Объединяет встроенные инструменты и MCP-инструменты,
    убирая дубликаты по имени (приоритет — встроенным)."""
    all_tools = list(TOOLS)
    if mcp_manager:
        all_tools += mcp_manager.get_tools()

    seen: set[str] = set()
    deduped: list[dict] = []
    for tool in all_tools:
        name = (tool.get("function") or {}).get("name")
        if not name:
            continue
        if name in seen:
            continue
        seen.add(name)
        deduped.append(tool)
    return deduped


# ---------- Выполнение инструментов ----------

async def execute_tool(name: str, args: dict) -> str:
    # ---- Встроенные инструменты ----
    if name in REGISTRY:
        if "path" in args:
            try:
                args["path"] = str(safe_path(args["path"]))
            except ValueError as e:
                return f"ERROR: {e}"

        # Автоснапшот перед правкой
        if name in SNAPSHOT_TOOLS:
            make_snapshot(name, args)

        # Подтверждение для опасных операций
        if name in DANGEROUS_TOOLS and not confirm(name, args):
            return "Пользователь отклонил выполнение."

        try:
            return str(REGISTRY[name](**args))
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

    # ---- MCP-инструменты ----
    if mcp_manager and mcp_manager.has_tool(name):
        if name in DANGEROUS_TOOLS and not confirm(name, args):
            return "Пользователь отклонил выполнение."
        return await mcp_manager.call_tool(name, args)

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

    TOKEN_STATS["prompt"] += p
    TOKEN_STATS["completion"] += c
    TOKEN_STATS["total"] += t
    TOKEN_STATS["cache_hit"] += ch
    TOKEN_STATS["cache_miss"] += cm
    TOKEN_STATS["requests"] += 1

    CONTEXT_SIZE = p


def _context_bar() -> str:
    if CONTEXT_LIMIT <= 0:
        return f"контекст: {fmt_num(CONTEXT_SIZE)} токенов"
    pct = min(100, int(CONTEXT_SIZE * 100 / CONTEXT_LIMIT))
    filled = int(pct / 5)
    bar = "█" * filled + "░" * (20 - filled)
    color = "green"
    if pct > 80:
        color = "red"
    elif pct > 60:
        color = "yellow"
    return (
        f"контекст: [{color}]{bar}[/{color}] "
        f"{fmt_num(CONTEXT_SIZE)}/{fmt_num(CONTEXT_LIMIT)} ({pct}%)"
    )


def _session_stats() -> str:
    s = TOKEN_STATS
    if s["requests"] == 0:
        return "токенов пока не потрачено"
    cache_info = ""
    if s["cache_hit"] or s["cache_miss"]:
        cache_info = f" | cache: {fmt_num(s['cache_hit'])} hit / {fmt_num(s['cache_miss'])} miss"
    return (
        f"[bold]сессия:[/bold] {s['requests']} зап. | "
        f"prompt: {fmt_num(s['prompt'])} | "
        f"completion: {fmt_num(s['completion'])} | "
        f"total: {fmt_num(s['total'])}{cache_info}"
    )


def print_stats(full: bool = False) -> None:
    ui_status(_context_bar())
    if full:
        s = TOKEN_STATS
        ui_print(f"""[bold]Статистика сессии[/bold]
  запросов:   {s['requests']}
  prompt:     {fmt_num(s['prompt'])}
  completion: {fmt_num(s['completion'])}
  total:      {fmt_num(s['total'])}
  cache hit:  {fmt_num(s['cache_hit'])}
  cache miss: {fmt_num(s['cache_miss'])}""")
    else:
        ui_status(_session_stats())


async def _call_model(messages: list, all_tools: list):
    if console:
        spinner = Spinner("dots", text=Text(" DeepSeek думает...", style="dim"))
        with Live(spinner, console=console, refresh_per_second=10, transient=True):
            try:
                return client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=all_tools,
                    tool_choice="auto",
                    temperature=TEMPERATURE,
                )
            except Exception as e:
                ui_error(f"API: {type(e).__name__}: {e}")
                return None
    else:
        print("... DeepSeek думает", end="", flush=True)
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=all_tools,
                tool_choice="auto",
                temperature=TEMPERATURE,
            )
            print("\r", end="")
            return response
        except Exception as e:
            print()
            ui_error(f"API: {type(e).__name__}: {e}")
            return None


async def _run_loop(messages: list) -> None:
    all_tools = build_tools_list()

    while True:
        response = await _call_model(messages, all_tools)
        if response is None:
            return

        _update_stats(getattr(response, "usage", None))

        msg = response.choices[0].message

        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:
            ui_print(f"💭 {reasoning}", style="dim italic")

        if not msg.tool_calls:
            print()
            ui_print(msg.content or "(пустой ответ)", style="markdown")
            print()
            print_stats()
            print()
            return

        messages.append(msg)

        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            ui_tool_call(name, args)
            result = await execute_tool(name, args)
            ui_tool_result(name, result)

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result[:8000],
            })


# ---------- Команды REPL ----------

def cmd_help() -> None:
    ui_print("""[bold]Команды:[/bold]
  [cyan]:help[/cyan]              — эта справка
  [cyan]:clear[/cyan]             — очистить историю диалога
  [cyan]:tokens[/cyan]            — статистика токенов за сессию
  [cyan]:context[/cyan]           — размер текущего контекста
  [cyan]:tools[/cyan]             — доступные инструменты
  [cyan]:skills[/cyan]            — загруженные навыки
  [cyan]:mcp[/cyan]               — статус MCP-серверов
  [cyan]:snapshots[/cyan]         — список снапшотов
  [cyan]:restore[/cyan]           — восстановить последний снапшот
  [cyan]:auto[/cyan]              — переключить режим подтверждений
  [cyan]:project[/cyan]           — показать корень проекта
  [cyan]:doctor[/cyan]            — диагностика (config, skills, mcp, утилиты)
  [cyan]:config[/cyan]            — путь к agent.config.json и текущие настройки
  [cyan]:exit[/cyan] или exit     — выход
""")


def cmd_tokens() -> None:
    if TOKEN_STATS["requests"] == 0:
        ui_info("Пока не было запросов к API.")
        return
    print_stats(full=True)


def cmd_context() -> None:
    ui_print(_context_bar())
    if CONTEXT_LIMIT > 0:
        left = max(0, CONTEXT_LIMIT - CONTEXT_SIZE)
        ui_info(f"Свободно в контексте: {fmt_num(left)} токенов")
        if CONTEXT_SIZE > CONTEXT_LIMIT * 0.8:
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


def cmd_skills() -> None:
    skills = load_project_skills()
    if not skills:
        ui_info("Навыки не найдены.")
        return
    for line in skills.splitlines():
        if line.startswith("### Skill:"):
            ui_print(f"· {line.replace('### Skill:', '').strip()}", style="cyan")


def cmd_mcp() -> None:
    if not mcp_manager or not mcp_manager.get_tools():
        ui_info("MCP-серверы не подключены.")
        return
    servers: dict[str, list[str]] = {}
    for tool_name, info in mcp_manager._tool_map.items():
        srv = info["server"]
        servers.setdefault(srv, []).append(tool_name)
    for srv, tools in servers.items():
        ui_print(f"[bold]{srv}[/bold]: {len(tools)} инструментов", style="cyan")


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

    import shutil
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


def cmd_doctor() -> None:
    import shutil

    ui_print("[bold]Диагностика агента[/bold]\n")
    ui_print(f"[cyan]AGENT_HOME:[/cyan]   {agent_home()}")
    ui_print(f"[cyan]agent.py:[/cyan]     {Path(__file__).resolve()}")
    ui_print(f"[cyan]PROJECT_ROOT:[/cyan] {PROJECT_ROOT}")
    ui_print(f"[cyan]cwd:[/cyan]          {Path.cwd()}\n")

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
    print()

    ui_print("[bold]Плагины[/bold]")
    dirs = plugins_candidates(PROJECT_ROOT)
    if dirs:
        for path in dirs:
            ui_print(f"  ✓ {path}")
    else:
        ui_print("  ~ папок plugins/ нет (ключ paths.plugins_dirs)", style="dim")
    print()

    ui_print("[bold]Утилиты[/bold]")
    for name in ("npx", "node", "uvx", "php", "python"):
        found = shutil.which(name)
        mark = "✓" if found else "✗"
        color = "green" if found else "dim"
        ui_print(f"  [{color}]{mark}[/{color}] {name}" +
                 (f"  {found}" if found else ""))


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
    elif c == ":skills":
        cmd_skills()
    elif c == ":mcp":
        cmd_mcp()
    elif c == ":snapshots":
        cmd_snapshots()
    elif c == ":restore":
        cmd_restore()
    elif c == ":auto":
        cmd_auto()
    elif c == ":project":
        ui_info(f"Проект: {PROJECT_ROOT}")
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
            session = PromptSession(history=InMemoryHistory())
        except Exception as e:
            # Нет настоящей консоли (пайп, CI, удалённый терминал) —
            # продолжаем с простым input().
            ui_info(f"prompt_toolkit недоступен ({type(e).__name__}), "
                    f"использую обычный ввод")
            session = None

    ui_print("[bold cyan]DeepSeek Agent[/bold cyan] — интерактивный режим")
    ui_info("Введите задачу или :help для списка команд. Выход — :exit или Ctrl+D.")
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
        try:
            await _run_loop(messages)
        except KeyboardInterrupt:
            print()
            ui_info("Прервано. Продолжаем сессию.")


# ---------- Точка входа ----------

async def main_async(args) -> None:
    global PROJECT_ROOT, CONFIRM_MODE, mcp_manager

    if not API_KEY:
        ui_error("Переменная окружения DEEPSEEK_API_KEY не установлена.")
        print('Windows:  setx DEEPSEEK_API_KEY "sk-..."')
        sys.exit(1)

    # Определяем корень проекта и перечитываем конфиги: -p > DEEPSEEK_PROJECT_ROOT
    # > конфиг в проекте > agent.config.json > cwd (папка запуска).
    PROJECT_ROOT = config_setup(args.project_root)
    if not PROJECT_ROOT.is_dir():
        ui_error(f"Папка не найдена: {PROJECT_ROOT}")
        sys.exit(1)

    if HAS_SNAPSHOT:
        snapshot.set_project_root(PROJECT_ROOT)

    if args.no_confirm or args.yes:
        CONFIRM_MODE = False

    ui_print(f"[bold]DeepSeek Agent[/bold]  ·  проект: [cyan]{PROJECT_ROOT}[/cyan]")
    ui_print(f"                ·  модель: [cyan]{MODEL}[/cyan]  "
             f"·  подтверждения: [cyan]{'выкл' if not CONFIRM_MODE else 'вкл'}[/cyan]")
    ui_info(f"агент: {agent_home()}")
    for conf in app_config.LOADED_CONFIGS:
        ui_info(f"конфиг: {conf}")
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
            await mcp_manager.connect(list(servers_by_name.values()))
            ui_info(f"MCP: {len(mcp_manager.get_tools())} инструментов "
                    f"из {len(servers_by_name)} серверов "
                    f"({', '.join(str(p) for p in mcp_paths)})")

    print()

    try:
        if args.task:
            system_prompt = build_system_prompt()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": args.task},
            ]
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
        description="DeepSeek CLI Agent — помощник по PHP/Python коду."
    )
    parser.add_argument("-p", "--project-root", default=None,
                        help="Корень проекта. По умолчанию — папка запуска (cwd), "
                             "если не задан в agent.config.json.")
    parser.add_argument("-t", "--task",
                        help="Разовая задача. Без неё — интерактивный REPL.")
    parser.add_argument("--no-confirm", action="store_true",
                        help="Отключить подтверждения.")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Алиас --no-confirm (для CI/автоматизации).")
    parser.add_argument("--show-tokens", action="store_true",
                        help="Показать статистику токенов после разовой задачи.")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print()
        ui_info("Прервано.")


if __name__ == "__main__":
    main()