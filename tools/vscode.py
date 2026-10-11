"""Мост к расширению VS Code: визуальная работа агента с проектом.

Расширение `vscode-extension/` поднимает локальный HTTP-сервер на 127.0.0.1 и
пишет в `<project>/.agent-cache/vscode-bridge.json` порт и токен доступа.
Этот модуль читает файл и отправляет команды: открыть файл в новой вкладке,
закрыть вкладку, показать файл в проводнике, открыть дифф со снапшотом.

Если расширение не запущено, инструменты возвращают понятное сообщение, а
агент продолжает работать как обычно (авто-открытие молча пропускается).

Мост можно поднять автоматически: `bootstrap()` запускает VS Code с проектом
через CLI `code` (если он есть в PATH) и ждёт появления моста. Агент вызывает
его на старте интерактивного режима, когда включён `vscode.auto_start`.

Настройки — секция "vscode" в agent.config.json (см. config.vscode_settings).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import config

BRIDGE_FILENAME = "vscode-bridge.json"
# Имя расширения-моста (vscode-extension/package.json) — для проверки установки.
BRIDGE_EXTENSION = "deepseek-agent-bridge"
DEFAULT_TIMEOUT = 5.0
# Сколько секунд по умолчанию ждать мост после запуска VS Code.
DEFAULT_START_WAIT = 8.0
# Имена CLI VS Code, которые ищем в PATH.
CODE_CLI_NAMES = ("code", "code.cmd", "code-insiders", "code-insiders.cmd")
# Короткая проверка «мост жив» и кэш к ней: available() вызывается часто
# (при сборке промпта и списка инструментов), а пинговать каждый раз незачем.
PROBE_TIMEOUT = 0.5
PROBE_TTL = 5.0

_log = logging.getLogger(__name__)

# Кэш результата последней проверки живости моста.
_probe: dict = {"at": 0.0, "alive": False}


class BridgeUnavailable(RuntimeError):
    """Мост к VS Code не запущен, отключён в конфиге или вернул ошибку."""


# ---------- Обнаружение моста ----------

def bridge_file(project_root: str | Path | None = None) -> Path:
    """Файл-дескриптор моста (его создаёт расширение VS Code)."""
    return config.cache_dir(project_root) / BRIDGE_FILENAME


def bridge_info(project_root: str | Path | None = None) -> dict | None:
    """Порт и токен моста либо None, если расширение не запущено.

    Файл-дескриптор может остаться после аварийного закрытия VS Code, поэтому
    одного его наличия мало — см. available().
    """
    path = bridge_file(project_root)
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        # Битый/недочитанный JSON — считаем, что моста нет, а не падаем.
        return None
    if not isinstance(data, dict) or _port(data) is None:
        return None
    return data


def _port(info: dict) -> int | None:
    """Порт моста как число либо None, если в файле мусор."""
    try:
        port = int(info.get("port"))
    except (TypeError, ValueError):
        return None
    return port if 0 < port < 65536 else None


def available(force: bool = False) -> bool:
    """Активен ли мост: интеграция включена и VS Code реально отвечает.

    Проверка живости (ping) кэшируется на PROBE_TTL секунд, чтобы не бить по
    HTTP при каждой сборке промпта. force=True — проверить прямо сейчас.
    """
    if not config.vscode_settings().get("enabled", True):
        return False

    info = bridge_info()
    if not info:
        _probe["at"] = time.monotonic()
        _probe["alive"] = False
        return False

    now = time.monotonic()
    if not force and (now - _probe["at"]) < PROBE_TTL:
        return bool(_probe["alive"])

    try:
        alive = bool(_call("ping", {}, timeout=PROBE_TIMEOUT))
    except BridgeUnavailable:
        alive = False

    _probe["at"] = now
    _probe["alive"] = alive
    return alive


# ---------- Пути ----------

def _abs(path: str) -> Path:
    """Абсолютный путь внутри проекта — та же песочница, что у инструментов."""
    root = Path(config.PROJECT_ROOT).resolve()
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"путь вне проекта запрещён: {path}")
    return p


def _rel(path: str | Path) -> str:
    """Путь относительно корня проекта (для сообщений пользователю)."""
    root = Path(config.PROJECT_ROOT).resolve()
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _latest_snapshot(path: Path) -> Path | None:
    """Самый свежий снапшот файла: .agent-cache/backups/<ts>/<отн. путь>."""
    root = Path(config.PROJECT_ROOT).resolve()
    backup = config.backup_dir(root)
    if not backup.is_dir():
        return None
    try:
        rel = path.resolve().relative_to(root)
    except ValueError:
        rel = Path(path.name)

    for entry in sorted(backup.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        candidate = entry / rel
        if candidate.is_file():
            return candidate
    return None


# ---------- Транспорт ----------

def _opener() -> urllib.request.OpenerDirector:
    """Опенер без прокси: мост живёт на 127.0.0.1 и через прокси ходить не должен."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _call(command: str, args: dict | None = None,
          timeout: float | None = None) -> dict:
    """Отправляет команду мосту и возвращает result.

    Бросает BridgeUnavailable, если интеграция выключена, расширение не
    запущено или мост вернул ошибку.
    """
    if not config.vscode_settings().get("enabled", True):
        raise BridgeUnavailable("интеграция с VS Code выключена (vscode.enabled=false)")

    info = bridge_info()
    if not info:
        raise BridgeUnavailable(
            "мост не найден — установите расширение vscode-extension/ "
            "и откройте проект в VS Code"
        )

    if timeout is None:
        timeout = float(config.vscode_settings().get("timeout") or DEFAULT_TIMEOUT)

    port = _port(info)
    if port is None:
        raise BridgeUnavailable(f"в {bridge_file()} нет корректного порта")

    payload = json.dumps({
        "token": info.get("token", ""),
        "command": command,
        "args": args or {},
    }).encode("utf-8")

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with _opener().open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise BridgeUnavailable(f"мост вернул HTTP {e.code}: {detail}")
    except (urllib.error.URLError, OSError) as e:
        raise BridgeUnavailable(f"нет связи с мостом (127.0.0.1:{port}): {e}")

    try:
        data = json.loads(body)
    except ValueError:
        raise BridgeUnavailable(f"некорректный ответ моста: {body[:200]}")

    if not data.get("ok"):
        raise BridgeUnavailable(str(data.get("error") or "неизвестная ошибка"))
    return data.get("result") or {}


# ---------- Инструменты агента ----------

def vscode_open(path: str, line: int = 1, column: int = 1,
                preview: bool = False, preserve_focus: bool = False) -> str:
    """Открывает файл в VS Code в новой вкладке и ставит курсор на строку.

    preserve_focus=True открывает вкладку, не забирая фокус у терминала.
    """
    try:
        target = _abs(path)
        result = _call("open", {
            "path": str(target),
            "line": int(line or 1),
            "column": int(column or 1),
            "preview": bool(preview),
            "preserve_focus": bool(preserve_focus),
        })
    except (BridgeUnavailable, ValueError) as e:
        return f"VS Code: не удалось открыть {path} — {e}"
    return f"VS Code: открыт {_rel(target)}:{result.get('line', line)}"


def vscode_close(path: str = "") -> str:
    """Закрывает вкладку файла.

    Без path — закрывает последнюю вкладку, открытую агентом.
    """
    args: dict = {}
    label = "последняя вкладка агента"
    if path:
        try:
            target = _abs(path)
        except ValueError as e:
            return f"VS Code: не удалось закрыть {path} — {e}"
        args["path"] = str(target)
        label = _rel(target)

    try:
        _call("close", args)
    except BridgeUnavailable as e:
        return f"VS Code: не удалось закрыть {label} — {e}"
    return f"VS Code: закрыт {label}"


def vscode_close_all() -> str:
    """Закрывает все вкладки, которые открыл агент."""
    try:
        result = _call("closeAll", {})
    except BridgeUnavailable as e:
        return f"VS Code: не удалось закрыть вкладки — {e}"
    return f"VS Code: закрыто вкладок агента: {result.get('closed', 0)}"


def vscode_reveal(path: str) -> str:
    """Показывает файл в проводнике VS Code (Explorer)."""
    try:
        target = _abs(path)
        _call("reveal", {"path": str(target)})
    except (BridgeUnavailable, ValueError) as e:
        return f"VS Code: не удалось показать {path} — {e}"
    return f"VS Code: показан в проводнике: {_rel(target)}"


def vscode_diff(path: str, original: str = "") -> str:
    """Открывает дифф файла со старой версией.

    original — путь к старой версии. Если не указан, берётся самый свежий
    снапшот файла из .agent-cache/backups (создаётся перед каждой правкой).
    """
    try:
        target = _abs(path)
    except ValueError as e:
        return f"VS Code: не удалось открыть дифф {path} — {e}"

    if original:
        try:
            left = _abs(original)
        except ValueError as e:
            return f"VS Code: не удалось открыть дифф {path} — {e}"
    else:
        left = _latest_snapshot(target)
        if left is None:
            return (f"VS Code: для {_rel(target)} нет снапшота "
                    "(правок ещё не было) — укажите original явно")

    try:
        _call("diff", {
            "path": str(target),
            "original": str(left),
            "title": f"{_rel(left)} ↔ {_rel(target)}",
        })
    except BridgeUnavailable as e:
        return f"VS Code: не удалось открыть дифф {path} — {e}"
    return f"VS Code: дифф открыт: {_rel(left)} ↔ {_rel(target)}"


def vscode_status() -> str:
    """Сообщает состояние моста (запущено ли расширение и отвечает ли оно)."""
    if not config.vscode_settings().get("enabled", True):
        return "VS Code: интеграция выключена (vscode.enabled = false)"

    info = bridge_info()
    if not info:
        return (f"VS Code: мост не найден, ожидается {bridge_file()} — "
                "расширение vscode-extension/ не запущено")

    if not available(force=True):
        return (f"VS Code: файл моста есть (порт {info.get('port')}), но сервер "
                "не отвечает — похоже, VS Code был закрыт аварийно. "
                "Перезапустите VS Code.")

    return (f"VS Code: мост активен — 127.0.0.1:{info.get('port')}, "
            f"проект {info.get('workspace')}")


# ---------- Автозапуск редактора (мост поднимается сам) ----------

def code_cli() -> str | None:
    """Путь к CLI VS Code (`code` / `code-insiders`) в PATH либо None."""
    for name in CODE_CLI_NAMES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _cli_argv(cli: str, *args: str) -> list[str]:
    """Команда запуска CLI: .cmd/.bat в Windows идут через командный интерпретатор."""
    if os.name == "nt" and cli.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", cli, *args]
    return [cli, *args]


def _spawn_detached(argv: list[str]) -> None:
    """Запускает процесс отдельно от агента (не держит консоль и не блокирует)."""
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)  # noqa: S603 — argv собирается из CLI в PATH


def wait_for_bridge(timeout: float | None = None,
                    interval: float = 0.4) -> dict | None:
    """Ждёт появления живого моста до timeout секунд. Возвращает его info или None."""
    if timeout is None:
        timeout = float(config.vscode_settings().get("start_wait") or DEFAULT_START_WAIT)
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        if available(force=True):
            return bridge_info()
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


_ext_cache: dict[str, bool] = {}


def extension_installed(cli: str | None = None, force: bool = False) -> bool:
    """Установлено ли расширение-мост в VS Code (ответ кэшируется на процесс)."""
    cli = cli or code_cli()
    if not cli:
        return False
    if not force and cli in _ext_cache:
        return _ext_cache[cli]

    installed = False
    try:
        proc = subprocess.run(  # noqa: S603 — cli берётся из PATH
            _cli_argv(cli, "--list-extensions"),
            capture_output=True, text=True, timeout=15, check=False,
        )
        installed = BRIDGE_EXTENSION in (proc.stdout or "").lower()
    except (OSError, subprocess.SubprocessError) as e:
        _log.debug("vscode --list-extensions: %s", e)

    _ext_cache[cli] = installed
    return installed


def bootstrap(project_root: str | Path | None = None,
              wait: float | None = None, force: bool = False) -> str:
    """Поднимает мост: запускает VS Code с проектом и ждёт ответа расширения.

    Возвращает короткий текст статуса для пользователя. Ничего не ломает:
    нет CLI, расширения или мост не ответил — вернётся подсказка, а агент
    продолжит работать как обычно.

    force=True — не сообщать «мост уже активен», а перезапустить проверку.
    """
    if not config.vscode_settings().get("enabled", True):
        return "интеграция с VS Code выключена (vscode.enabled = false)"

    info = bridge_info(project_root)
    if info and available(force=True) and not force:
        return f"мост уже активен: 127.0.0.1:{info.get('port')}"

    cli = code_cli()
    if not cli:
        return ("CLI VS Code (`code`) не найден в PATH — откройте проект в VS Code "
                "вручную (File → Open Folder): расширение поднимет мост само")

    if not extension_installed(cli):
        return ("расширение deepseek-agent-bridge не установлено — см. "
                "vscode-extension/README.md (быстро: "
                "code --install-extension <путь>.vsix)")

    root = Path(project_root or config.PROJECT_ROOT).resolve()
    try:
        _spawn_detached(_cli_argv(cli, str(root)))
    except OSError as e:
        return f"не удалось запустить VS Code ({cli}): {e}"

    if wait is None:
        wait = float(config.vscode_settings().get("start_wait") or DEFAULT_START_WAIT)
    info = wait_for_bridge(wait)
    if info:
        return f"VS Code запущен, мост активен: 127.0.0.1:{info.get('port')}"
    return (f"VS Code запущен, но мост не ответил за {int(wait)} с — "
            "проверьте индикатор «DeepSeek: мост» в статус-баре (:vscode)")


# ---------- Авто-открытие после правки ----------

def auto_open(path: str) -> str:
    """Открывает правленный файл в VS Code (вызывается после write/edit).

    Возвращает короткое примечание для модели или пустую строку, если
    интеграция выключена/недоступна или открыть не удалось.
    """
    settings = config.vscode_settings()
    if not settings.get("enabled", True) or not settings.get("auto_open", True):
        return ""
    if not available():
        return ""

    if settings.get("auto_close_previous"):
        try:
            _call("close", {})
        except BridgeUnavailable:
            pass

    try:
        target = _abs(path)
        _call("open", {
            "path": str(target),
            "line": 1,
            "column": 1,
            "preview": False,
            # Не забираем фокус у терминала — иначе во время работы агента
            # ввод «уезжает» из консоли в редактор.
            "preserve_focus": True,
        })
    except (BridgeUnavailable, ValueError) as e:
        _log.debug("vscode auto_open(%s): %s", path, e)
        return ""
    return f"VS Code: открыт {_rel(target)}"
