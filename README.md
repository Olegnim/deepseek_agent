# DeepSeek CLI Agent

CLI-агент на Python для написания и правки кода (**PHP**, **Python**, **JS/TS**, веб) через DeepSeek API. Работает на **Windows**, **Linux (Ubuntu/Debian)** и **macOS**.

Возможности: инструменты (чтение/правка файлов, grep, shell, git, веб-поиск без ключей), **автолинт синтаксиса** после каждой правки, **навыки** (skills) и **профили** (роли) агента, **снапшоты** правок с откатом, подключение внешних **MCP-серверов**.

> **Кроссплатформенность.** Примеры даны для Windows/PowerShell. На Linux/macOS: замените `python` → `python3`, а обратные слэши в путях `\` → `/`. Все команды, кроме установки переменной окружения, одинаковы.

```
<AGENT_HOME>/                 # папка агента — определяется автоматически из расположения agent.py
├── agent.py                  # точка входа
├── config.py                 # поиск конфигов, project_root, agent_home
├── agent.config.json         # настройки агента (шаблон для git, без секретов)
├── mcp_integration.py        # клиент MCP-серверов
├── skills_loader.py          # загрузка навыков
├── tools/                    # filesystem, shell, linter, git, web, vscode, cache, snapshot, stack, loop_guard
├── skills/                   # встроенные навыки (project-навыки подхватятся отдельно)
├── plugins/                  # (опционально) доп. модули
├── .agent.config.json        # ЛОКАЛЬНЫЙ оверрайд и секреты (в git не попадает)
├── .vscode/tasks.json        # готовые задачи VS Code
├── vscode-extension/         # расширение-мост: агент открывает файлы прямо в VS Code
└── mcp_config.json           # MCP-серверы (пути — через ${project_root})
```

`AGENT_HOME` — папка агента (`agent.py`, `tools/`, `skills/`), `PROJECT_ROOT` — проект, с которым работает агент (папка запуска). Оба определяются автоматически, прописывать пути не нужно.

---

## Быстрый старт

### 1. Python 3.10 или новее

```powershell
python --version
```

Не найден? Установите с [python.org](https://www.python.org/downloads/) (в установщике — галка **Add python.exe to PATH**).
**Linux/macOS:** `sudo apt install python3 python3-venv python3-pip` (Debian/Ubuntu) или `brew install python3` (macOS).

### 2. Зависимости

```powershell
python -m pip install -r "<AGENT_HOME>\requirements.txt"
# если файла под рукой нет:
python -m pip install openai mcp rich prompt_toolkit
```

`openai` и `mcp` обязательны; `rich` и `prompt_toolkit` — только для цветного вывода и истории команд (без них агент работает в упрощённом режиме).

### 3. Проверка установки (API-ключ не нужен)

```powershell
python "<AGENT_HOME>\agent.py" --doctor
```

Покажет пути, найденные конфиги, навыки, MCP-серверы, доступные утилиты и статус пакетов/ключа. Если в блоке «Пакеты Python» есть `✗ openai`/`✗ mcp` — вернитесь к шагу 2.

### 4. API-ключ DeepSeek (только через переменную окружения)

```powershell
# Windows
setx DEEPSEEK_API_KEY "sk-ваш-ключ"
```

```bash
# Linux / macOS — на текущую сессию; постоянно — добавьте строку в ~/.bashrc или ~/.zshrc
export DEEPSEEK_API_KEY="sk-ваш-ключ"
```

Перезапустите терминал (для `setx`). Имя переменной задаётся ключом `api.api_key_env` (по умолчанию `DEEPSEEK_API_KEY`).

> Ключ храните **только в переменной окружения**. Альтернативно его можно положить в `api.api_key` локального (не в git) `.agent.config.json`, но переменная окружения — приоритетнее и безопаснее.

### 5. Запуск из папки проекта

```powershell
cd "<PROJECT_ROOT>"                        # корень вашего проекта
python "<AGENT_HOME>\agent.py"             # интерактивный режим
python "<AGENT_HOME>\agent.py" -t "Проверь синтаксис PHP в src и исправь ошибки"   # разовая задача
```

Корень проекта агент берёт из папки запуска, свою папку — из расположения `agent.py`. **Не запускайте агент из его собственной папки** — иначе корнем проекта станет сама папка агента (тогда задайте `-p <PROJECT_ROOT>`).

### (Опционально) Виртуальное окружение

```powershell
# Windows
python -m venv "<AGENT_HOME>\.venv"
"<AGENT_HOME>\.venv\Scripts\Activate.ps1"
python -m pip install -r "<AGENT_HOME>\requirements.txt"
```

```bash
# Linux / macOS
python3 -m venv "<AGENT_HOME>/.venv"
source "<AGENT_HOME>/.venv/bin/activate"
python -m pip install -r "<AGENT_HOME>/requirements.txt"
```

Признак активированного окружения — `(.venv)` в приглашении. Если PowerShell запрещает запуск `Activate.ps1` — `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

---

## Команды интерактивного режима

| Команда | Что делает |
|---|---|
| `:help` | Справка |
| `:clear` | Очистить историю диалога |
| `:doctor` | Диагностика (config, skills, mcp, снапшоты, утилиты) |
| `:config` / `:project` | Показать настройки и корень проекта |
| `:tools` | Список инструментов |
| `:lint [файл]` | Автолинт вручную; без аргумента — список проверок |
| `:skills` | Загруженные навыки |
| `:profile [имя]` / `:profiles` | Активный профиль / переключить / список профилей |
| `:mcp` | Статус MCP-серверов |
| `:vscode` | Статус моста к VS Code |
| `:vscode start` | Запустить VS Code с проектом и поднять мост (то же — `:vscode restart`) |
| `:snapshots` / `:restore` | Список снапшотов / откатить последний |
| `:cache` / `:cache clear` | Объём кэша и очистка / очистить сразу |
| `:tokens` / `:context` / `:log` | Токены / размер контекста / путь к логу сессии |
| `:auto` | Вкл/выкл подтверждения |
| `:exit` | Выход (также `exit`, `quit`, `:q`) |

---

## Инструменты агента

| Инструмент | Назначение |
|---|---|
| `read_file`, `read_range` | Чтение файла целиком / диапазона строк |
| `write_file`, `edit_file` | Запись файла / точечная замена (`replace_all=true` — все вхождения) |
| `list_dir`, `grep` | Список файлов / поиск по regex (фильтр по расширению) |
| `run_shell` | Shell-команды (`php -l`, `node --check`, `pytest`); таймаут — `tools.shell_timeout` |
| `git_status`, `git_diff`, `git_log` | Состояние репозитория (только чтение) |
| `web_search`, `fetch_url` | Поиск (DuckDuckGo) и чтение страниц без API-ключей |
| `vscode_open`, `vscode_close`, `vscode_close_all` | Открыть файл в новой вкладке VS Code / закрыть вкладку / закрыть все вкладки агента |
| `vscode_reveal`, `vscode_diff`, `vscode_status` | Показать файл в проводнике / дифф со снапшотом / статус моста |

**Автолинт:** после `write_file`/`edit_file` агент сам проверяет синтаксис по правилам из секции `lint` (`php -l`, `node --check`, `python -m py_compile`, `javac`, `kotlinc`, `swiftc`) и добавляет результат к ответу. Утилита не найдена или правила нет — шаг пропускается. Отключить: `"lint": { "enabled": false }`.

**Работа в VS Code (`vscode`):** если установлено расширение из `vscode-extension/`, агент открывает правленые файлы в новых вкладках, умеет их закрывать, показывать в проводнике и открывать дифф со снапшотом — работу агента видно прямо в редакторе. Расширение поднимает **мост** на `127.0.0.1` и пишет порт с токеном в `.agent-cache/vscode-bridge.json`.

Интеграция **необязательная и отказоустойчивая**: если VS Code не запущен, расширение не установлено, файл-дескриптор битый или мост не отвечает — инструменты `vscode_*` просто не показываются модели, авто-открытие пропускается, агент работает как обычно. Никаких исключений и зависаний; принудительно выключается через `"vscode": { "enabled": false }`.

Как поднять мост (три шага или вообще без ручной работы) — раздел [«Мост к VS Code»](#мост-к-vs-code-агент-открывает-файлы-в-редакторе). Установка расширения — [`vscode-extension/README.md`](vscode-extension/README.md) (Windows / Linux / macOS).

**Кэш (`.agent-cache`):** внутри проекта лежат снапшоты (`backups/`), логи (`logs/`) и история (`history.txt`). В git не попадает; чистится через `:cache clear` или `--clear-cache`.

---

## Флаги `agent.py`

| Флаг | Описание |
|---|---|
| `-p, --project-root` | Корень проекта (по умолчанию — папка запуска) |
| `-t, --task` | Разовая задача; без флага — интерактивный режим |
| `--profile <имя>` | Профиль (роль): `php`, `python`, `frontend`, `java`, `kotlin`, `swift` или свой |
| `--list-profiles` | Список профилей и выход (ключ не нужен) |
| `--doctor` | Диагностика окружения и выход (ключ не нужен) |
| `--clear-cache` / `--no-cache-ask` | Очистить кэш перед стартом / не спрашивать про очистку |
| `-y, --yes` / `--no-confirm` | Без запросов подтверждения (для автоматизации) |
| `--show-tokens` | Статистика токенов после разовой задачи |
| `-h, --help` | Справка |

```powershell
python "<AGENT_HOME>\agent.py" --doctor                      # проверить установку
python "<AGENT_HOME>\agent.py" -t "Найди все TODO в src"     # разовая задача
python "<AGENT_HOME>\agent.py" -p "D:/work/site" -t "php -l" # другой проект
python "<AGENT_HOME>\agent.py" --profile php                 # роль PHP-разработчика
```

---

## Как агент находит проект и настройки

| Понятие | Как определяется |
|---|---|
| `AGENT_HOME` | Автоматически из расположения `agent.py`. Переопределяется переменной `DEEPSEEK_AGENT_HOME` |
| `PROJECT_ROOT` | Автоматически = папка запуска (cwd). Песочница: инструменты не выйдут за её пределы |

Приоритет `PROJECT_ROOT`: `-p` > `DEEPSEEK_PROJECT_ROOT` > `.agent.config.json` в папке запуска > `agent.config.json` > cwd.

Общие ресурсы ищутся по цепочке «проект → папка агента» и объединяются: `skills/`, `mcp_config.json` / `.mcp.json`, `plugins/`. Настройки: проектный конфиг > `agent.config.json` > дефолты в `config.py`.

Всё проверяется одной командой: `--doctor` (или `:config` в сессии) — покажет `agent_home`, `project_root`, `cwd`, список прочитанных конфигов и действующие значения.

**Ключевые настройки** (`agent.config.json`, полный список — в файле и в комментариях):

| Ключ | Смысл |
|---|---|
| `api.api_key_env` / `api.model` | Имя переменной с ключом / модель |
| `agent.profile` | Профиль (роль); пусто = авто по стеку |
| `agent.max_steps` | Лимит шагов модели на задачу; `0` = без лимита (защита от зацикливания — `loop_guard`) |
| `agent.instructions` | Доп. правила проекта (строка/список, попадают в промпт) |
| `paths.project_root` | Пусто = папка запуска |
| `paths.mcp_config` / `paths.skills_dir` / `paths.backup_dir` | Пути к MCP-конфигам / навыкам / снапшотам |
| `lint.enabled` / `lint.rules` | Автолинт и правила (`{file}` — путь к файлу) |
| `tools.shell_timeout` | Таймаут shell-команд, сек |
| `tools.web.*` | Веб-поиск: `enabled`, `timeout`, `max_chars`, `results` |
| `snapshots.max_backups` | Сколько последних снапшотов хранить |

В строках JSON работают подстановки: `${env:VAR}`, `${agent_home}` (${agent_dir}), `${project_root}`. Абсолютные пути в JSON пишите через прямые слэши (`D:/work/site`).

---

## Навыки (skills) и профили

**Навык** — папка с файлом `SKILL.md`, содержимое которого подмешивается в системный промпт:

```
<PROJECT_ROOT>/skills/php-conventions/SKILL.md
```

```markdown
---
name: php-conventions
description: Правила для PHP-кода в этом проекте
applies_to: [php]          # необязательно: подключать только для этого стека
---

- Используй `declare(strict_types=1);` в каждом файле.
- Избегай `var_dump`, `print_r` в коммитах.
```

Навыки проекта (`<PROJECT_ROOT>/skills/`) и агента (`<AGENT_HOME>/skills/`) **объединяются**; одноимённый проектный перекрывает агентский. Без `applies_to` навык подключается всегда. Определённый стек и загруженные навыки видны в `--doctor` и `:skills`.

Встроенные навыки: `code-quality` (всегда), `php-conventions`, `php-web`, `python-conventions`, `java-conventions`, `kotlin-conventions`, `android`, `swift-conventions`, `ios`, `web-frontend`.

**Профиль (роль)** привязывает агента к языку: грузятся только его навыки, `applies_to` не учитывается.

```powershell
python "<AGENT_HOME>\agent.py" --list-profiles     # какие есть
python "<AGENT_HOME>\agent.py" --profile php       # роль PHP-разработчика
```

Внутри сессии: `:profile python` — переключить, `:profile auto` — авто по стеку. Постоянно — ключом `"agent": { "profile": "php" }`. Свой профиль добавляется секцией `profiles` в `agent.config.json` (код агента менять не нужно).

---

## Подключение MCP-серверов

Создайте `mcp_config.json` в корне проекта или рядом с агентом (ищутся и объединяются автоматически):

```json
{
  "mcpServers": {
    "filesystem": {
      "enabled": true,
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "${project_root}"]
    }
  }
}
```

- Абсолютные пути не нужны — используйте `${project_root}` (`${agent_dir}` и `${env:VAR}` тоже доступны).
- `npx` требует Node.js, `uvx` — `uv`. Первый запуск может занять 10–30 секунд.
- Сервер с `"enabled": false` пропускается. Статус — по `:mcp`.
- MCP-инструменты, меняющие файлы/выполняющие команды, проходят через подтверждение (отключается `--yes`).

---

## Интеграция с VS Code

### Мост к VS Code: агент открывает файлы в редакторе

Расширение из `vscode-extension/` поднимает в VS Code локальный HTTP-мост. Пока он жив, агент открывает правленые файлы в новых вкладках, показывает их в проводнике и открывает дифф со снапшотом — работа агента видна прямо в редакторе.

**Запуск — три шага:**

1. **Установите расширение** (один раз). Проще всего — папкой расширений, без сборки и Node.js:

   ```powershell
   # Windows (PowerShell) — junction на папку vscode-extension
   New-Item -ItemType Junction -Path "$env:USERPROFILE\.vscode\extensions\deepseek-agent-bridge" -Target "<AGENT_HOME>\vscode-extension"
   ```

   ```bash
   # Linux / macOS — симлинк
   ln -s "<AGENT_HOME>/vscode-extension" ~/.vscode/extensions/deepseek-agent-bridge
   ```

   Другие варианты (VSIX через `npx @vscode/vsce`, отладка через F5) — в [`vscode-extension/README.md`](vscode-extension/README.md).

2. **Откройте проект в VS Code**: `code <PROJECT_ROOT>` (или **File → Open Folder**). В статус-баре появится индикатор `DeepSeek: мост`.

3. **Запустите агента.** Если VS Code уже открыт с проектом, ничего делать не нужно — мост найдётся сам, а в шапке агента будет строка `VS Code: мост активен (127.0.0.1:…)`.

**Автозапуск (агент поднимает редактор сам).** При старте интерактивного режима агент проверяет мост и, если его нет, сам запускает VS Code с проектом (CLI `code` из PATH) и ждёт мост до `vscode.start_wait` секунд. Ничего не мешает работе: нет `code` в PATH или расширение не установлено — будет короткая подсказка, а агент продолжит как обычно. Для разовых задач (`-t "…"`) автозапуск не выполняется, чтобы не открывать редактор в скриптах.

* запустить/перезапустить вручную в сессии: `:vscode start` (`:vscode restart` — даже если мост уже активен);
* проверить состояние: `:vscode` или `python agent.py --doctor` (блок **VS Code**);
* выключить автозапуск: `"vscode": { "auto_start": false }` в `agent.config.json`.

**Настройки** (секция `vscode` в `agent.config.json`):

| Ключ | По умолчанию | Описание |
|---|---|---|
| `enabled` | `true` | `false` — инструменты `vscode_*` не показываются модели. |
| `auto_open` | `true` | Открывать файл после `write_file` / `edit_file`. |
| `auto_close_previous` | `false` | Перед открытием нового файла закрывать предыдущую вкладку агента. |
| `timeout` | `5` | Таймаут HTTP-запроса к мосту, секунды. |
| `auto_start` | `true` | На старте самому запускать VS Code, если моста нет. |
| `start_wait` | `8` | Сколько секунд ждать мост после запуска VS Code. |

### Запуск агента задачами VS Code

`.vscode/tasks.json` из репозитория уже готов (команда `python`/`python3` выбирается по ОС): откройте папку **своего проекта** в VS Code и запустите задачу через **Ctrl+Shift+P → `Tasks: Run Task` → `DeepSeek: …`**. Терминал VS Code стартует в корне проекта, поэтому `-p` не нужен.

Если `tasks.json` лежит в другом проекте — используйте в нём `${env:DEEPSEEK_AGENT_HOME}/agent.py` и задайте переменную с путём к папке агента (`setx DEEPSEEK_AGENT_HOME "..."` / `export DEEPSEEK_AGENT_HOME="..."`).

---

## Частые проблемы

| Симптом | Решение |
|---|---|
| `python` не найден / открывается Microsoft Store | Установите Python 3.10+ и отметьте **Add python.exe to PATH**; новый терминал. На Linux/macOS используйте `python3`. Отключить заглушку Store: `Параметры → Приложения → Псевдонимы выполнения приложения` |
| `ERROR: переменная окружения DEEPSEEK_API_KEY не установлена` | Задайте переменную (`setx` / `export`) и перезапустите терминал — либо `api.api_key` в локальном `.agent.config.json` |
| `pip` ставит пакеты «не туда», агент не видит `openai`/`mcp` | Пакеты и агент должны использовать один интерпретатор: `python -m pip -V` и `python -c "import sys; print(sys.executable)"`; активируйте venv в том же терминале |
| `Could not find a version that satisfies the requirement mcp` | Региональное зеркало pip без свежих пакетов: `python -m pip install mcp -i https://mirrors.aliyun.com/pypi/simple/` |
| Агент работает не с тем проектом | Корень = папка запуска. Не запускайте из папки агента; проверьте `--doctor`/`:config`, задайте `-p`, `DEEPSEEK_PROJECT_ROOT` или `.agent.config.json` |
| `JSONDecodeError` при старте | Битый конфиг (лишняя запятая, неэкранированный `\`). Абсолютные пути — через прямые слэши `D:/work/site` |
| MCP-сервер не подключается | Проверьте `npx`/`uvx` в PATH, запустите команду сервера вручную, проверьте `"enabled"` и раскрытие `${project_root}` (запуск из папки проекта) |
| Консоль показывает «кракозябры» | Агент сам переключает вывод в UTF-8; используйте Windows Terminal / PowerShell 7, для старых консолей — `chcp 65001` |
| `Путь вне проекта запрещён` | Так и задумано (песочница). Проверьте корень — `:project`/`:config` |
| `:vscode`: «мост не найден» | Расширение не установлено или VS Code не открыт с проектом. Поднимите автоматически: `:vscode start` (или `auto_start: false` → откройте проект сами). Установка расширения — `vscode-extension/README.md` |
| `:vscode`: «файл моста есть, но VS Code не отвечает» | VS Code закрылся аварийно — `:vscode restart` или перезапустите редактор |
| Автозапуск пишет «CLI VS Code (`code`) не найден в PATH» | В PATH нет команды `code`: в VS Code выполните **Ctrl+Shift+P → `Shell Command: Install 'code' command in PATH`**, затем перезапустите терминал |
| `ERROR: команда не завершилась за 60 секунд` | Таймаут `tools.shell_timeout` — увеличьте или дробите команды |
| `fetch_url`: «запрос отклонён (SSRF-защита)» | Читаются только публичные адреса; для локальных сервисов — `run_shell` (`curl http://127.0.0.1:8124`) |
| Много снапшотов/логов, поиск тормозит | `:cache clear` или `--clear-cache` (удаляется только `.agent-cache`) |

---

## Лицензия

MIT — используйте, форкайте, адаптируйте под себя.
