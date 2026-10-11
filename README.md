# DeepSeek CLI Agent

CLI-агент на Python для написания и правки **PHP** и **Python** кода через DeepSeek API. Работает на Windows, поддерживает навыки (skills), инструменты (tools) и подключение внешних **MCP-серверов** (Model Context Protocol).

```
deepseek-agent/                 # = AGENT_HOME, определяется автоматически
├── agent.py                    # точка входа
├── config.py                   # автопоиск конфигов, project_root, agent_home
├── agent.config.json           # настройки агента (путей в коде нет)
├── mcp_integration.py          # клиент MCP-серверов
├── skills_loader.py            # загрузка навыков
├── tools/
│   ├── __init__.py             # реестр инструментов и их схемы
│   ├── filesystem.py           # read/write/edit/list/grep
│   ├── shell.py                # запуск команд (php -l, pytest)
│   └── snapshot.py             # автоснапшоты перед правкой
├── skills/                     # навыки агента (проектные подхватятся отдельно)
│   └── php-conventions/
│       └── SKILL.md
├── plugins/                    # (опционально) доп. модули агента
├── .agent-cache/backups/       # автоснапшоты правок (создаётся в папке проекта, откат — :restore)
├── .agent.config.json          # ЛОКАЛЬНЫЙ оверрайд и секреты (в git не попадает)
├── .vscode/tasks.json          # готовые задачи VS Code для запуска агента
└── mcp_config.json             # MCP-серверы (пути — через ${project_root})
```

Рабочий проект (`PROJECT_ROOT`) — отдельная папка: он не обязан содержать файлы агента, но может добавить свои `skills/`, `mcp_config.json`, `plugins/` и `.agent.config.json` — всё это подхватится автоматически.

> В примерах ниже путь к папке агента обозначен как `<AGENT_HOME>` — подставьте свой (та папка, где лежит `agent.py`). Путь к рабочему проекту — `<PROJECT_ROOT>` (папка, открытая в VS Code). Реальных путей и ключей в репозитории нет и быть не должно.



## Быстрый старт

1. Откройте в VS Code **папку своего проекта** (`File → Open Folder…`).
2. Откройте встроенный терминал (`Terminal → New Terminal`) — он стартует в корне проекта.
3. Один раз задайте API-ключ (подробнее — раздел 3): `setx DEEPSEEK_API_KEY "sk-..."` и перезапустите терминал.
4. Запустите агента по его собственному пути, подставив свою папку вместо `<AGENT_HOME>`:

```powershell
python "<AGENT_HOME>\agent.py" -t "Проверь синтаксис PHP в src и исправь ошибки"
```

Корень проекта агент берёт из cwd (папка открытого проекта), свою папку — из расположения `agent.py`. Прописывать абсолютные пути в конфигах не нужно.

### Интерактивный режим

Запускать из встроенного терминала VS Code, открытого на папке **вашего проекта** (см. раздел 4):

```powershell
python "<AGENT_HOME>\agent.py"
```

Доступные команды:

| Команда | Что делает |
|---|---|
| `:help` | Справка |
| `:clear` | Очистить историю диалога |
| `:tokens` | Статистика токенов за сессию |
| `:context` | Размер текущего контекста и остаток лимита |
| `:tools` | Список инструментов |
| `:skills` | Загруженные навыки (проект + агент) |
| `:mcp` | Статус MCP-серверов |
| `:snapshots` | Список автоснапшотов правок |
| `:restore` | Откатить последний снапшот |
| `:config` | `agent_home`, `project_root`, прочитанные конфиги, текущие настройки |
| `:auto` | Вкл/выкл подтверждения |
| `:project` | Показать корень проекта |
| `:doctor` | Диагностика (config, skills, mcp, снапшоты, утилиты) |
| `:exit` | Выход (также `exit`, `quit`, `:q`) |

### Дополнительные зависимости для UI

```powershell
pip install prompt_toolkit rich -i https://mirrors.aliyun.com/pypi/simple/
```

Без них агент работает в упрощённом режиме.


---

## 0. Как агент понимает пути

Никаких абсолютных путей в коде. Есть два независимых понятия, и **оба определяются автоматически**:

| Понятие | Что это | Как определяется |
|---|---|---|
| `AGENT_HOME` | Папка самого агента: `agent.py`, `tools/`, `skills/`, `plugins/`, `mcp_config.json` | Автоматически из расположения `agent.py`. Переопределяется `DEEPSEEK_AGENT_HOME` (нужно только для запуска из `site-packages` или ярлыка) |
| `PROJECT_ROOT` | Проект, с которым работаем. Песочница: инструменты не выйдут за её пределы | Автоматически = **папка запуска** (cwd), то есть корень, открытый в терминале VS Code |

Приоритет `PROJECT_ROOT`: `-p` > `DEEPSEEK_PROJECT_ROOT` > `.agent.config.json` в папке запуска > `agent.config.json` > cwd.

**Общие ресурсы ищутся по цепочке «проект → папка агента»** и объединяются:

- навыки: `<project>/skills/` + `<AGENT_HOME>/skills/` (проектный одноимённый навык перекрывает агентский);
- MCP-конфиги: `<project>/mcp_config.json`, `<project>/.mcp.json` + `<AGENT_HOME>/…` (серверы проекта приоритетнее по имени);
- плагины: `<project>/plugins/` + `<AGENT_HOME>/plugins/`.

Поэтому запускать агента можно откуда угодно — модули подтянутся сами.

### Конфиги (оба необязательны)

**`<AGENT_HOME>/agent.config.json`** — базовые настройки агента. Это шаблон для коммита: путь к ключу здесь задаётся, а сам ключ — нет (значение `api_key` должно быть пустым, секреты храните только в локальном `.agent.config.json`, который уже в `.gitignore`):

```json
{
  "api": {
    "api_key_env": "DEEPSEEK_API_KEY",
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "temperature": 0.2,
    "context_limit": 65536
  },
  "paths": {
    "project_root": "",
    "skills_dir": "skills",
    "mcp_config": ["mcp_config.json", ".mcp.json"],
    "backup_dir": ".agent-cache/backups",
    "plugins_dirs": ["plugins"]
  },
  "snapshots": { "max_backups": 50 }
}
```

**`<PROJECT_ROOT>/.agent.config.json`** — необязательный оверрайд для конкретного проекта (подхватывается автоматически, если агент запущен из папки проекта). Файл **не коммитится** (см. `.gitignore`) — именно здесь держите секреты: `api_key`, свой `temperature`/`backup_dir`:

```json
{
  "api": { "api_key": "sk-ваш-ключ", "temperature": 0.7 },
  "paths": { "backup_dir": ".agent-cache/backups" }
}
```

| Ключ | Смысл |
|---|---|
| `paths.project_root` | Пусто = папка запуска. Указывать здесь абсолютный путь нужно только если агент стартует не из проекта |
| `paths.mcp_config` | Строка или список имён конфигов MCP. Относительные ищутся в проекте и в `AGENT_HOME`; можно задать абсолютный путь |
| `paths.skills_dir` | Папка навыков (относительная — ищется в проекте, затем у агента) |
| `paths.backup_dir` | Куда складывать автоснапшоты (относительный путь — от проекта) |
| `paths.plugins_dirs` | Папки плагинов/доп. модулей |
| `snapshots.max_backups` | Сколько последних снапшотов хранить |
| `api.*` | Ключ (env предпочтительнее), модель, base_url, temperature, лимит контекста. Секреты — только в локальном `.agent.config.json` |

**Подстановки внутри строк JSON:** `${env:VAR_NAME}`, `${agent_home}` (синоним `${agent_dir}`), `${project_root}`. Благодаря им `mcp_config.json` не содержит путей:

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

**Приоритет настроек:** проектный конфиг > `agent.config.json` > дефолты в `config.py`.

Проверка: `:config` (или `python "<AGENT_HOME>\agent.py" -t "покажи конфиг"`) покажет `agent_home`, `project_root`, список прочитанных конфигов и все действующие значения.

---

## 1. Требования

- **Windows 10/11** (работает и на Linux/macOS, но команды ниже — для PowerShell)
- **Python 3.10+** — MCP SDK требует минимум 3.10
- **Node.js** (нужен, если будете подключать MCP-серверы через `npx`)
- **uv** (нужен для MCP-серверов через `uvx`, опционально)

Проверьте версии:

```powershell
python --version
node --version
```

Если Python ниже 3.10 — установите новый с [python.org](https://www.python.org/downloads/) и в установщике отметьте **Add Python to PATH**.

---

## 2. Установка зависимостей

### ⚠️ Важно про зеркало pip

По умолчанию pip может использовать **Tsinghua TUNA** (`pypi.tuna.tsinghua.edu.cn`), на котором свежие пакеты вроде `mcp` часто отсутствуют. Все команды ниже используют **Aliyun** как надёжное зеркало.

### 2.1. Основные зависимости

```powershell
pip install openai mcp -i https://mirrors.aliyun.com/pypi/simple/
```

Если хотите поставить MCP с CLI-инструментами (`mcp dev`, `mcp run`):

```powershell
pip install "mcp[cli]" -i https://mirrors.aliyun.com/pypi/simple/
```

### 2.2. (Рекомендуется) Резервный источник для pip

Чтобы в будущем `pip install <пакет>` работал без `-i`, добавьте Aliyun как резервный индекс:

```powershell
pip config set global.extra-index-url "https://mirrors.aliyun.com/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/"
```

Теперь обычная команда `pip install openai` сможет взять пакет из резервного источника, если основного не хватает.

### 2.3. Проверка установки

```powershell
python -c "import openai, mcp; print('openai', openai.__version__); print('mcp ok')"
```

Должно вывести версию `openai` и `mcp ok`.

### 2.4. Если установка всё равно падает

- Обновите pip: `python -m pip install --upgrade pip`
- Очистите кэш: `pip cache purge`
- Попробуйте другой индекс: `pip install mcp -i https://mirrors.cloud.tencent.com/pypi/simple/`
- Проверьте, что Python 3.10+: `python --version`

---

## 3. Настройка API-ключа DeepSeek

Ключ берётся из переменной окружения (имя задаётся в `api.api_key_env`, по умолчанию `DEEPSEEK_API_KEY`), а если её нет — из `api.api_key` в **локальном** `.agent.config.json` (он не коммитится, см. `.gitignore`).

> ⚠️ Никогда не публикуйте реальный ключ: `.agent.config.json`, `agent.config.local.json`, `mcp_config.local.json` и `.mcp.json` уже в `.gitignore`. Если ключ всё-таки попал в git или в публичный файл — сразу отзовите его в консоли DeepSeek и выпустите новый.

Рекомендуемый способ — переменная окружения, её достаточно задать **один раз**:

```powershell
setx DEEPSEEK_API_KEY "sk-ваш-ключ"
```

**Перезапустите PowerShell** (или откройте новое окно) — переменные, установленные через `setx`, применяются к новым сессиям.

Проверка:

```powershell
echo $env:DEEPSEEK_API_KEY
```

Без ключа в окружении агент возьмёт `api.api_key` из локального `.agent.config.json` (в репозиторий его не добавляйте).

---

## 4. Запуск

**Правильный сценарий:** открываете в VS Code **папку своего проекта** (`File → Open Folder…`), затем во встроенном терминале (`Terminal → New Terminal`) запускаете агент по его собственному пути. Терминал VS Code стартует уже в корне проекта, поэтому:

- `PROJECT_ROOT` = папка проекта (cwd терминала);
- `AGENT_HOME` = папка, где лежит `agent.py` (определяется автоматически из его расположения).

```text
<AGENT_HOME>\                  # папка, где лежит агент (путь подставьте свой)
└── agent.py
```

### 4.1. Разовая задача из терминала VS Code открытого проекта

Так выглядит команда: терминал открыт в папке проекта, агент вызывается по своему пути (пути абстрактные — подставьте свои):

```powershell
# терминал открыт в <PROJECT_ROOT>, агент лежит в <AGENT_HOME>
python "<AGENT_HOME>\agent.py" -t "Проверь синтаксис PHP и исправь ошибки"
```

Корень проекта агент берёт из cwd, поэтому предыдущий сценарий (`cd <PROJECT_ROOT>` + полный путь к `agent.py`) работает без дополнительных флагов.

> Не нужно `cd` в папку агента: если запустить `python agent.py` **из папки агента**, корнем проекта станет сама папка агента. В этом случае либо задайте `-p <PROJECT_ROOT>`, либо `paths.project_root` / `.agent.config.json`.

### 4.2. Разовый запуск для другого проекта

Флаг `-p` перекрывает автоопределение:

```powershell
python "<AGENT_HOME>\agent.py" -p "<PROJECT_ROOT>" -t "Найди все TODO в src"
```

Агент будет работать внутри указанной папки и не выйдет за её пределы.

### 4.3. Интерактивный режим

```powershell
python "<AGENT_HOME>\agent.py"
```

Спросит задачу в начале, потом будет ждать следующую после каждого ответа. Выход — `exit`, `quit` или `:q`.

### 4.4. Без подтверждений (для автоматизации)

```powershell
python "<AGENT_HOME>\agent.py" -t "Запусти php -l на всех файлах src" --yes
```

Флаги `--no-confirm` / `--yes` отключают запросы подтверждения для `write_file`, `edit_file` и `run_shell`.

---

## 5. Навыки (skills)

Навык — это папка с файлом `SKILL.md`, содержимое которого подмешивается в системный промпт. Так агент узнаёт правила вашего проекта.

Структура:

```
your-project/
└── skills/
    └── php-conventions/
        └── SKILL.md
```

Пример `SKILL.md`:

```markdown
---
name: php-conventions
description: Правила для PHP-кода в этом проекте
---

- Используй `declare(strict_types=1);` в каждом файле.
- Классы — в namespace `App\`, PSR-4 автозагрузка.
- После правки PHP-файла запускай `php -l <file>`.
- Избегай `var_dump`, `print_r` в коммитах.
```

Агент ищет навыки в двух местах **и объединяет их**: `<PROJECT_ROOT>/skills/` (навыки проекта) и `<AGENT_HOME>/skills/` (навыки самого агента). Если навык с таким именем есть в обоих — выигрывает проектный. Папку можно переопределить ключом `paths.skills_dir`.

---

## 6. Подключение MCP-серверов

MCP (Model Context Protocol) позволяет агенту использовать инструменты внешних серверов: filesystem, git, sqlite, memory и другие — без написания кода под каждый.

### 6.1. Создайте `mcp_config.json` в корне проекта или рядом с агентом

Конфиги ищутся автоматически (`paths.mcp_config`, по умолчанию `mcp_config.json` и `.mcp.json`): сначала в проекте, затем в `AGENT_HOME`. Найденные конфиги **объединяются** — серверы проекта приоритетнее одноимённых агентских. Так можно держать общий набор серверов у агента и добавлять проектные.

```json
{
  "mcpServers": {
    "filesystem": {
      "enabled": true,
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "${project_root}"
      ]
    },
    "git": {
      "enabled": false,
      "command": "uvx",
      "args": ["mcp-server-git", "--repository", "${project_root}"]
    }
  }
}
```

Путь приходит из корня проекта — **абсолютные пути в `mcp_config.json` не нужны**. Сервер с `"enabled": false` просто пропускается.

**Обратите внимание:**
- Абсолютные пути не нужны — используйте `${project_root}`. Если всё же нужен абсолютный путь, в JSON пишите его через **прямые слэши** (`<диск>:/путь/к/проекту`) или экранируйте каждый обратный слэш (`<диск>:\\путь\\к\\проекту`): неэкранированные обратные слэши сломают парсинг JSON.
- Кроме `${project_root}` доступны `${agent_dir}` (синоним `${agent_home}`) и `${env:VAR_NAME}`.
- `npx` требует установленного Node.js; `uvx` — установленного `uv`.
- Первый запуск сервера через `npx`/`uvx` может занять 10–30 секунд — это нормально.

### 6.2. Запустите агента

При старте он автоматически найдёт `mcp_config.json` (путь — `paths.mcp_config`) и подключит серверы:

```
[MCP] подключён: filesystem (11 инструментов)
[MCP] подключён: git (9 инструментов)
MCP: 20 инструментов из 2 серверов (mcp_config.json)
```

Число инструментов и список найденных конфигов у вас будут свои; статус в любой момент виден по `:mcp`.

Все MCP-инструменты доступны модели наравне с обычными (`read_file`, `grep`, `run_shell` и т.д.).

### 6.3. Безопасность

- MCP-инструменты, изменяющие файлы или выполняющие команды, проходят через `confirm()`. Отключается флагом `--yes` — используйте только в доверенных сценариях.
- Сервер `@modelcontextprotocol/server-filesystem` принимает список разрешённых директорий в `args`. Не давайте ему корень диска (например `C:/`) — только папку проекта.
- Никогда не коммитьте секреты: `api_key` и локальные оверрайды держите в `.agent.config.json` (он в `.gitignore`).

---

## 7. Интеграция с VS Code

Файл `.vscode/tasks.json` из этого репозитория уже готов: путь к агенту задан через `${workspaceFolder}`, флага `-p` нет — корень проекта VS Code передаёт сам как cwd задачи. Хардкода диска нет.

То есть: откройте в VS Code папку **своего проекта** и запускайте задачи — агент сам поймёт, что корень проекта это папка воркспейса. Запуск из встроенного терминала VS Code (Terminal → New Terminal) работает так же: cwd терминала = корень проекта.

Если `tasks.json` лежит в другом проекте, используйте `${env:DEEPSEEK_AGENT_HOME}/agent.py` — один раз задайте переменную с **своим** путём к папке агента и перезапустите VS Code:

```powershell
setx DEEPSEEK_AGENT_HOME "<AGENT_HOME>"
```

Пример `tasks.json` (тот же, что в репозитории):

```json
{
  "version": "2.0.0",
  "_comment": "Пути не хардкодятся: корень проекта агент берёт сам из cwd задачи (= папка открытого воркспейса), папку агента вычисляет из расположения agent.py. Флаг -p нужен только для явного переопределения.",
  "tasks": [
    {
      "label": "DeepSeek: run task",
      "type": "shell",
      "command": "python",
      "args": [
        "${workspaceFolder}/agent.py",
        "-t", "${input:agentTask}"
      ],
      "presentation": { "panel": "new", "reveal": "always" },
      "problemMatcher": []
    },
    {
      "label": "DeepSeek: interactive",
      "type": "shell",
      "command": "python",
      "args": ["${workspaceFolder}/agent.py"],
      "presentation": { "panel": "dedicated", "reveal": "always" },
      "problemMatcher": []
    },
    {
      "label": "DeepSeek: doctor",
      "type": "shell",
      "command": "python",
      "args": ["${workspaceFolder}/agent.py", "-t", "покажи диагностику окружения"],
      "presentation": { "panel": "new", "reveal": "always" },
      "problemMatcher": []
    }
  ],
  "inputs": [
    {
      "id": "agentTask",
      "type": "promptString",
      "description": "Задача для агента",
      "default": "Проверь синтаксис PHP и исправь ошибки"
    }
  ]
}
```

Запуск: **Ctrl+Shift+P** → `Tasks: Run Task` → `DeepSeek: run task`.

---

## 8. Все доступные флаги `agent.py`

| Флаг | Описание |
|---|---|
| `-p, --project-root` | Корень проекта. По умолчанию — папка запуска (cwd) |
| `-t, --task` | Задача для агента. Если не указана — интерактивный режим |
| `--no-confirm` | Не спрашивать подтверждения для опасных операций |
| `-y, --yes` | Алиас для `--no-confirm` |
| `--show-tokens` | Показать статистику токенов после разовой задачи |

---

## 9. Частые проблемы

**`ERROR: Could not find a version that satisfies the requirement mcp`**
Используйте Aliyun-зеркало: `pip install mcp -i https://mirrors.aliyun.com/pypi/simple/`. Если не помогает — проверьте версию Python (нужна 3.10+).

**`ERROR: переменная окружения DEEPSEEK_API_KEY не установлена`**
Выполните `setx DEEPSEEK_API_KEY "sk-..."` и **перезапустите PowerShell** — либо впишите ключ в `api.api_key` в локальном `.agent.config.json` (не в отслеживаемый git `agent.config.json`).

**`[config] ... JSONDecodeError` при старте**
Сломан один из конфигов (`agent.config.json` / `.agent.config.json`) — лишняя запятая, неэкранированные обратные слэши. Абсолютный путь в JSON указывайте через прямые слэши (`<диск>:/путь/к/проекту`). Имя битого файла видно в сообщении.

**В логе `[MCP] <сервер>: не раскрыта подстановка ${project_root}`**
Сервер запускается из конфига, где `${project_root}` не во что раскрыть. Запустите агента из папки проекта (или укажите корень через `-p`), чтобы подстановка `${project_root}` раскрылась.

**Агент работает не с тем проектом**
Корень = папка запуска (cwd). Типичная причина — агент запущен из **своей** папки, а не из папки проекта. Проверьте `:config` (строки `project_root` и `cwd`) — при необходимости задайте `-p <PROJECT_ROOT>`, переменную `DEEPSEEK_PROJECT_ROOT` или `.agent.config.json` в проекте.

**MCP-сервер не подключается**
Проверьте, что `npx` или `uvx` доступны в PATH (`npx --version`). Попробуйте запустить команду сервера вручную из PowerShell — увидите реальную ошибку. Также убедитесь, что `"enabled"` не выставлен в `false`.

**Агент пишет «Путь вне проекта запрещён»**
Все пути в tool calls приводятся к корню проекта: агент намеренно не выходит за пределы песочницы. Проверьте корень командой `:project` / `:config`.

**Долгий первый запуск MCP**
Первый `npx -y @modelcontextprotocol/server-filesystem` скачивает пакет из npm — это может занять 20–30 секунд. Второй запуск будет быстрым.

---

## 10. Лицензия

MIT — используйте, форкайте, адаптируйте под себя.