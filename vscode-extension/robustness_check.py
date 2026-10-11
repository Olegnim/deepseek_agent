"""Проверка устойчивости: агент не должен падать без VS Code и с битым мостом.

Запускать из корня проекта:

    python vscode-extension/robustness_check.py

Скрипт временно подменяет .agent-cache/vscode-bridge.json (файла не было —
он удаляется в конце) и проверяет четыре сценария: моста нет, дескриптор
битый, порт в дескрипторе мусорный, мост есть но не отвечает. Плюс —
что сам агент в этих условиях скрывает инструменты vscode_* и молча
пропускает авто-открытие. Возвращает код 1, если хоть одна проверка упала.
"""

import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from tools import vscode as vscode_tools

root = Path(config.PROJECT_ROOT)
bridge = vscode_tools.bridge_file(root)
had_bridge = bridge.is_file()

results = []


def check(name, ok, extra=""):
    results.append((ok, name, extra))


def reset():
    vscode_tools._probe["at"] = 0.0
    vscode_tools._probe["alive"] = False


def write_bridge(text):
    bridge.parent.mkdir(parents=True, exist_ok=True)
    bridge.write_text(text, encoding="utf-8")


# --- 1. Моста нет вовсе ---
if bridge.exists():
    bridge.unlink()
reset()
check("no bridge: available() is False", vscode_tools.available() is False)
check("no bridge: bridge_info() is None", vscode_tools.bridge_info(root) is None)
check("no bridge: auto_open() is ''", vscode_tools.auto_open("agent.py") == "")
check("no bridge: open returns message",
      vscode_tools.vscode_open("agent.py").startswith("VS Code:"))
check("no bridge: close returns message",
      vscode_tools.vscode_close().startswith("VS Code:"))
check("no bridge: close_all returns message",
      vscode_tools.vscode_close_all().startswith("VS Code:"))
check("no bridge: reveal returns message",
      vscode_tools.vscode_reveal("README.md").startswith("VS Code:"))
check("no bridge: diff returns message",
      vscode_tools.vscode_diff("agent.py").startswith("VS Code:"))
check("no bridge: status says not found", "не найден" in vscode_tools.vscode_status())

# --- 2. Битый JSON ---
write_bridge("{ this is not json")
reset()
check("broken json: bridge_info() is None", vscode_tools.bridge_info(root) is None)
check("broken json: available() is False", vscode_tools.available() is False)
check("broken json: auto_open() is ''", vscode_tools.auto_open("agent.py") == "")

# --- 3. Порт-мусор ---
write_bridge(json.dumps({"port": "abc", "token": "t"}))
reset()
check("garbage port: bridge_info() is None", vscode_tools.bridge_info(root) is None)
check("garbage port: available() is False", vscode_tools.available() is False)

# --- 4. Порт вне диапазона ---
write_bridge(json.dumps({"port": 99999, "token": "t"}))
reset()
check("port 99999: bridge_info() is None", vscode_tools.bridge_info(root) is None)

# --- 5. Мост есть, но мёртв (порт свободен) ---
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
free_port = sock.getsockname()[1]
sock.close()
write_bridge(json.dumps({"port": free_port, "token": "t", "workspace": str(root)}))
reset()
started = time.monotonic()
alive = vscode_tools.available(force=True)
elapsed = time.monotonic() - started
check("dead bridge: available() is False", alive is False)
check(f"dead bridge: probe is fast ({elapsed:.2f}s)", elapsed < 3.0)
check("dead bridge: status mentions restart",
      "не отвечает" in vscode_tools.vscode_status())
check("dead bridge: auto_open() is ''", vscode_tools.auto_open("agent.py") == "")

# --- 6. Сам агент: инструменты и промпт без моста ---
import agent  # noqa: E402  (импорт после подготовки окружения)

names = {(t.get("function") or {}).get("name") for t in agent.build_tools_list()}
leaked = names & agent.VSCODE_TOOLS
check("agent: vscode tools hidden while bridge is down", not leaked, str(sorted(leaked)))
check("agent: system prompt builds", "Ты CLI-агент" in agent.build_system_prompt())

out = agent._auto_open_in_vscode("write_file", {"path": str(root / "agent.py")}, "Записано")
check("agent: auto open is silent when bridge is down", out == "Записано")

out = agent._auto_open_in_vscode("read_file", {"path": str(root / "agent.py")}, "текст")
check("agent: auto open ignores non-edit tools", out == "текст")

out = agent._auto_open_in_vscode("write_file", {"path": str(root / "agent.py")}, "ERROR: nope")
check("agent: auto open skips failed edits", out == "ERROR: nope")

# --- Очистка ---
if had_bridge:
    write_bridge(json.dumps({"port": free_port, "token": "t"}))
else:
    bridge.unlink(missing_ok=True)

failed = [r for r in results if not r[0]]
for ok, name, extra in results:
    print(("PASS  " if ok else "FAIL  ") + name + ("  -> " + extra if extra else ""))
print()
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
