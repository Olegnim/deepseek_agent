"""Запуск shell-команд. Рабочая директория — корень проекта.

Раньше команды выполнялись из папки запуска агента, хотя инструмент
документирован как «path — относительно корня проекта». Теперь cwd
выставляется явно из config.PROJECT_ROOT, поэтому относительные пути
в командах (php -l src/File.php) совпадают с путями инструментов.
"""

import os
import subprocess

import config


def run_shell(command: str) -> str:
    """Запускает shell-команду с ограничением по времени.
    При таймауте убивает всю группу процессов, а не только родителя."""
    try:
        working_dir = config.PROJECT_ROOT
        kwargs = dict(
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,   # <-- важно: не давать потомкам читать stdin
            cwd=str(working_dir) if working_dir.is_dir() else None,
        )
        if os.name == "nt":
            # На Windows — отдельная группа процессов, чтобы kill задел всех
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        r = subprocess.run(command, **kwargs)
        return f"exit={r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"

    except subprocess.TimeoutExpired as e:
        # Попытаться убить группу (Windows)
        if os.name == "nt" and e.pid:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(e.pid)],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass
        return "ERROR: команда не завершилась за 60 секунд и была прервана."

    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"