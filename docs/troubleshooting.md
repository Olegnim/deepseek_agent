# Частые проблемы

| Симптом | Решение |
|---|---|
| `python` не найден / открывается Microsoft Store | На Windows: установите Python 3.10+ и отметьте **Add python.exe to PATH**; новый терминал. На macOS/Linux команды `python` обычно нет — используйте `python3`. Отключить заглушку Store: `Параметры → Приложения → Псевдонимы выполнения приложения` |
| `No module named pytest` при запуске тестов | pytest не установлен или стоит в другом интерпретаторе: `python -m pip install -r requirements-dev.txt`, затем сверьте `python -c "import sys; print(sys.executable)"` и `python -m pip -V`. В `--doctor` блок **Пакеты Python** показывает `✓ pytest` и актуальную команду установки |
| `ERROR: переменная окружения DEEPSEEK_API_KEY не установлена` | Задайте переменную (`setx` / `export`) и перезапустите терминал — либо `api.api_key` в локальном `.agent.config.json` |
| `pip` ставит пакеты «не туда», агент не видит `openai`/`mcp` | Пакеты и агент должны использовать один интерпретатор: `python -m pip -V` и `python -c "import sys; print(sys.executable)"`; активируйте venv в том же терминале |
| `error: externally-managed-environment` (Ubuntu 24.04+, Debian 12+) | Системный Python защищён PEP 668. Активируйте venv (`python3 -m venv …` + `source …/bin/activate`) и ставьте зависимости в него, либо разово `python3 -m pip install --break-system-packages -r requirements.txt` |
| `Could not find a version that satisfies the requirement mcp` | Региональное зеркало pip без свежих пакетов: `python -m pip install mcp -i https://mirrors.aliyun.com/pypi/simple/` |
| Агент работает не с тем проектом | Корень = папка запуска. Не запускайте из папки агента; проверьте `--doctor`/`:config`, задайте `-p`, `DEEPSEEK_PROJECT_ROOT` или `.agent.config.json` |
| `JSONDecodeError` при старте | Битый конфиг (лишняя запятая, неэкранированный `\`). Абсолютные пути — через прямые слэши `D:/work/site` |
| MCP-сервер не подключается | Проверьте `npx`/`uvx` в PATH, запустите команду сервера вручную, проверьте `"enabled"` и раскрытие `${project_root}` (запуск из папки проекта). На Windows агенту не нужно писать `npx.cmd`: команда ищется в PATH сама, а `.cmd`/`.bat` запускаются через `cmd /c` |
| В stderr сервера: `Client does not support MCP Roots, using allowed directories set from server args` | Это информационная строка сервера (например, `server-filesystem`), а не ошибка: клиент не объявил capability `roots`, и сервер взял папки из своих аргументов. Агент объявляет `roots` сам — проверьте, что PATH папок существует и что версия кода свежая (`:config`, строка `mcp_roots:`; расширить список — секция `mcp.roots`) |
| Консоль показывает «кракозябры» | Агент сам переключает вывод в UTF-8; используйте Windows Terminal / PowerShell 7, для старых консолей — `chcp 65001` |
| `Путь вне проекта запрещён` | Так и задумано (песочница). Проверьте корень — `:project`/`:config` |
| «файл не найден», хотя файл есть | Разное написание имени: регистр (`src/file.py` vs `SRC/File.py`) или Unicode-форма (macOS хранит имена в NFD, а модель присылает NFC). Агент подбирает фактическое имя сам — проверьте путь в `:project` и точное имя в `list_dir`/`grep` |
| Windows: `OSError`/`WinError 206` при снапшоте («слишком длинный путь») | Снапшоты повторяют структуру проекта внутри `.agent-cache/backups/<дата>/`, и путь удлиняется. Включите длинные пути (`git config --system core.longpaths true` и/или политика `LongPathsEnabled` в реестре) или вынесите кэш из проекта: в `agent.config.json` укажите `paths.backup_dir` = `${env:TEMP}/deepseek-agent-backups` |
| `:vscode`: «мост не найден» | Расширение не установлено или VS Code не открыт с проектом. Поднимите автоматически: `:vscode start` (или `auto_start: false` → откройте проект сами). Установка расширения — [`../vscode-extension/README.md`](../vscode-extension/README.md) |
| `:vscode`: «файл моста есть, но VS Code не отвечает» | VS Code закрылся аварийно — `:vscode restart` или перезапустите редактор |
| Автозапуск пишет «CLI VS Code (`code`) не найден в PATH» | В PATH нет команды `code`: в VS Code выполните **Ctrl+Shift+P → `Shell Command: Install 'code' command in PATH`**, затем перезапустите терминал |
| `ERROR: команда не завершилась за 60 секунд` | Таймаут `tools.shell_timeout` — увеличьте или дробите команды |
| `fetch_url`: «запрос отклонён (SSRF-защита)» | Читаются только публичные адреса; для локальных сервисов — `run_shell` (`curl http://127.0.0.1:8124`) |
| Много снапшотов/логов, поиск тормозит | `:cache clear` или `--clear-cache` (удаляется только `.agent-cache`) |
