"""Запуск shell-команд. Рабочая директория — корень проекта.

Раньше команды выполнялись из папки запуска агента, хотя инструмент
документирован как «path — относительно корня проекта». Теперь cwd
выставляется явно из config.PROJECT_ROOT, поэтому относительные пути
в командах (php -l src/File.php) совпадают с путями инструментов.

Кроссплатформенность:
- команда выполняется через системный shell (`cmd.exe` на Windows, `/bin/sh`
  на Linux/macOS) — обычные команды вроде `php -l src/File.php` работают везде;
- дочерний процесс запускается в отдельной сессии/группе
  (`start_new_session` на POSIX, `CREATE_NEW_PROCESS_GROUP` на Windows),
  поэтому при таймауте убивается вся группа процессов, а не только родитель.
"""

import os
import signal
import subprocess

import config


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Убивает процесс и всех его потомков.

    На POSIX дочерний процесс — лидер собственной сессии
    (start_new_session=True), поэтому killpg заденет всю группу.
    На Windows помогает taskkill с флагом /T (дерево процессов).
    """
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        # Процесс уже завершился или группу не достать — прибиваем сам процесс.
        try:
            proc.kill()
        except OSError:
            pass


def run_shell(command: str) -> str:
    """Запускает shell-команду с ограничением по времени (tools.shell_timeout).
    При таймауте убивает всю группу процессов, а не только родителя."""
    timeout = config.shell_timeout()
    working_dir = config.PROJECT_ROOT

    popen_kwargs = dict(
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",           # не падать на не-UTF8 выводе утилит
        stdin=subprocess.DEVNULL,   # <-- важно: не давать потомкам читать stdin
        cwd=str(working_dir) if working_dir.is_dir() else None,
    )
    if os.name == "nt":
        # На Windows — отдельная группа процессов, чтобы kill задел всех.
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        # На Linux/macOS — отдельная сессия: тот же эффект через killpg.
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(command, **popen_kwargs)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return f"exit={proc.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            proc.communicate(timeout=5)   # собрать вывод и дождаться перезапуска
        except Exception:
            pass
        return f"ERROR: команда не завершилась за {timeout} секунд и была прервана."
    except Exception as e:
        _kill_process_tree(proc)
        return f"ERROR: {type(e).__name__}: {e}"
