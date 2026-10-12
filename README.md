# DeepSeek CLI Agent

CLI-агент на Python для написания и правки кода (**PHP**, **Python**, **JS/TS**, веб) через DeepSeek API. Работает на **Windows**, **Linux (Ubuntu/Debian)** и **macOS**.

Возможности: инструменты (чтение/правка файлов, grep, shell, git, веб-поиск без ключей), **автолинт синтаксиса** после каждой правки, **навыки** (skills) и **профили** (роли) агента, **снапшоты** правок с откатом, подключение внешних **MCP-серверов**.

> **Кроссплатформенность.** Примеры в основном даны для Windows/PowerShell. На Linux/macOS: замените `python` → `python3`, а обратные слэши в путях `\` → `/`. Все команды, кроме установки переменной окружения, одинаковы.
>
> **Про `python` и `python3`.** На Windows интерпретатор обычно доступен как `python` (или `py`), на macOS/Linux — как `python3`. Сам агент к этой разнице устойчив: автолинт Python-файлов, подсказки в промпте и `--doctor` используют интерпретатор, которым запущен агент (`sys.executable`), а не жёстко зашитое имя команды. Поэтому там, где ниже написано `python`, на macOS/Linux подставляйте `python3`.

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
# Windows
python --version      # если не найден — попробуйте: py --version
```

```bash
# Linux / macOS
python3 --version
```

Не найден? Установите с [python.org](https://www.python.org/downloads/) (в установщике — галка **Add python.exe to PATH**).
**Linux/macOS:** `sudo apt install python3 python3-venv python3-pip` (Debian/Ubuntu) или `brew install python3` (macOS).

Проверить, каким интерпретатором пользуется агент, можно в любой момент: `python3 agent.py --doctor` — в блоке **Утилиты** есть строка «интерпретатор агента».

### 2. Зависимости

```powershell
# Windows
python -m pip install -r "<AGENT_HOME>\requirements.txt"
# если файла под рукой нет:
python -m pip install openai mcp rich prompt_toolkit
```

```bash
# Linux / macOS
python3 -m pip install -r "<AGENT_HOME>/requirements.txt"
```

> **Ubuntu 24.04 и новее (PEP 668).** Системный Python помечен как externally
> managed, поэтому `python3 -m pip install` без виртуального окружения падает
> с `error: externally-managed-environment`. Правильный путь — виртуальное
> окружение (раздел «Виртуальное окружение» ниже). Разовое исключение —
> `python3 -m pip install --break-system-packages -r …`, но так пакеты уезжают
> в системный Python и могут конфликтовать с пакетами из `apt`.

`openai` и `mcp` обязательны; `rich` и `prompt_toolkit` — только для цветного вывода и истории команд (без них агент работает в упрощённом режиме).

### 3. Проверка установки (API-ключ не нужен)

```powershell
python "<AGENT_HOME>\agent.py" --doctor
```

```bash
# Linux / macOS
python3 "<AGENT_HOME>/agent.py" --doctor
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

```bash
# Linux / macOS
cd "<PROJECT_ROOT>"
python3 "<AGENT_HOME>/agent.py"
python3 "<AGENT_HOME>/agent.py" -t "Проверь синтаксис PHP в src и исправь ошибки"
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

Правила для Python (`python -m py_compile`) выполняются **интерпретатором самого агента** (`sys.executable`), поэтому работают и на macOS/Linux, где команды `python` нет, и на Windows с `py`-launcher-ом (`py -3 …` тоже понимается). Байткод линта складывается во временный каталог системы (`PYTHONPYCACHEPREFIX`), а не в `__pycache__` проекта — автолинт не мусорит в чужом репозитории.

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
| `mcp.roots` | Папки, которые агент объявляет MCP-серверам как разрешённые (roots/list); пусто = корень проекта |
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

### Разрешённые папки (roots/list)

Агент объявляет серверам разрешённые папки сам — протоколом MCP roots, а не только аргументами команды:

- по умолчанию это корень проекта (`paths.project_root`);
- папки из `args` сервера добавляются автоматически, поэтому доступ не сужается;
- список можно расширить секцией `mcp.roots` в `agent.config.json` (относительные пути — от корня проекта, `${project_root}` работает):

```json
{ "mcp": { "roots": ["${project_root}", "~/shared"] } }
```

Если сервер пишет в stderr `Client does not support MCP Roots, using allowed directories set from server args` — значит клиент не объявил capability `roots`; агент версии ≥ этого изменения объявляет её, как только есть хотя бы одна существующая папка. Посмотреть, что объявлено, можно командой `:config` (строка `mcp_roots:`) или инструментом `filesystem__list_allowed_directories`.

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

`.vscode/tasks.json` из репозитория уже готов (команда `python`/`python3` выбирается по ОС): откройте папку **своего проекта** в VS Code и запустите задачу через **Ctrl+Shift+P → `Tasks: Run Task` → `DeepSeek: …`**. Терминал VS Code стартует в корне проекта, поэтому `-p` не нужен. Задача `DeepSeek: tests (pytest)` запускает `pytest` в папке агента (на macOS/Linux — `python3 -m pytest`, на Windows — `python -m pytest`).

Если `tasks.json` лежит в другом проекте — используйте в нём `${env:DEEPSEEK_AGENT_HOME}/agent.py` и задайте переменную с путём к папке агента (`setx DEEPSEEK_AGENT_HOME "..."` / `export DEEPSEEK_AGENT_HOME="..."`).

---

## Частые проблемы

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
| `:vscode`: «мост не найден» | Расширение не установлено или VS Code не открыт с проектом. Поднимите автоматически: `:vscode start` (или `auto_start: false` → откройте проект сами). Установка расширения — `vscode-extension/README.md` |
| `:vscode`: «файл моста есть, но VS Code не отвечает» | VS Code закрылся аварийно — `:vscode restart` или перезапустите редактор |
| Автозапуск пишет «CLI VS Code (`code`) не найден в PATH» | В PATH нет команды `code`: в VS Code выполните **Ctrl+Shift+P → `Shell Command: Install 'code' command in PATH`**, затем перезапустите терминал |
| `ERROR: команда не завершилась за 60 секунд` | Таймаут `tools.shell_timeout` — увеличьте или дробите команды |
| `fetch_url`: «запрос отклонён (SSRF-защита)» | Читаются только публичные адреса; для локальных сервисов — `run_shell` (`curl http://127.0.0.1:8124`) |
| Много снапшотов/логов, поиск тормозит | `:cache clear` или `--clear-cache` (удаляется только `.agent-cache`) |

---

## Тесты

```powershell
# Windows
python -m pip install -r "<AGENT_HOME>\requirements-dev.txt"   # pytest
cd "<AGENT_HOME>"
python -m pytest                      # все тесты, ~3 секунды
python -m pytest tests/test_config.py -v
```

```bash
# Linux / macOS
python3 -m pip install -r "<AGENT_HOME>/requirements-dev.txt"
cd "<AGENT_HOME>"
python3 -m pytest
python3 -m pytest tests/test_config.py -v
```

Если `python -m pytest` пишет «No module named pytest» — pytest поставлен не в тот интерпретатор: сверьте `python -c "import sys; print(sys.executable)"` с выводом `python -m pip -V` (в `--doctor` есть блок **Пакеты Python** с пометкой о pytest).

Тесты не ходят в сеть, не обращаются к DeepSeek API и не требуют внешних
утилит: модель подменяется заглушками, страницы — фейковым «опенером», а
временные проекты создаются в `tmp_path`. Что проверяется:

| Файл | Что покрывает |
|---|---|
| `tests/test_config.py` | приоритет корня проекта (`-p` > env > конфиг > cwd), слоистые конфиги, подстановки (в т.ч. `${project_root}`), лимиты, профили, пути к ресурсам, выбор Python-команды |
| `tests/test_filesystem.py` | `read_file`/`read_range` (границы и обрезка), `write_file`, `edit_file` (первое вхождение, `replace_all`, CRLF/LF), `grep`, схема проекта |
| `tests/test_linter.py` | выбор правила по расширению, OK/ОШИБКА, пропуск без утилиты, подстановка интерпретатора, отсутствие `__pycache__` в проекте, добавление отчёта к правке |
| `tests/test_agent_core.py` | песочница `safe_path`, выполнение инструментов, снапшот+линт вокруг `write_file`, отказ пользователя, список инструментов для модели, системный промпт, команды REPL, токены, настройки API из конфига проекта |
| `tests/test_agent_loop.py` | цикл задачи: пары assistant→tool, ошибки инструментов и битый JSON аргументов, loop-guard, лимит шагов, сбой API, ретраи |
| `tests/test_stack_skills.py` | определение стека по маркерным файлам, front-matter `SKILL.md`, отбор навыков по `applies_to` и по профилю |
| `tests/test_snapshot_cache.py` | снапшоты (путь, лимит `max_backups`), подсчёт и очистка `.agent-cache` |
| `tests/test_loop_guard.py` | предупреждение, остановка, сброс счётчика при другом результате |
| `tests/test_web.py` | SSRF-фильтр адресов, преобразование HTML, разбор выдачи DuckDuckGo (без сети) |
| `tests/test_mcp.py` | конфиг MCP, подстановки, схемы инструментов, префикс `сервер__инструмент`, ошибки вызова, roots/list |
| `tests/test_vscode.py` | дескриптор моста и битые данные, песочница путей, сообщения при закрытом редакторе |
| `tests/test_shell_git.py` | рабочая папка и код возврата shell, убийство команды по таймауту, git status/diff/log (включая русский текст в диффе) |

Прогон должен быть полностью зелёным: известные дефекты 0.1.0 (настройки
`api.*` при `-p`, `${project_root}` в конфиге, секция `tools.lint`, кодировка
вывода git) исправлены — `xfail`-маркеров в тестах больше нет.

---

## Лицензия

MIT — используйте, форкайте, адаптируйте под себя.
