# DeepSeek CLI Agent

CLI-агент на Python для написания и правки кода (**PHP**, **Python**, **JS/TS**, веб) через DeepSeek API. Работает на Windows, поддерживает навыки (skills), **профили (роли) агента**, **автолинт синтаксиса**, **защиту от зацикливания**, инструменты (tools), **поиск в интернете** (web_search/fetch_url, без API-ключей) и подключение внешних **MCP-серверов** (Model Context Protocol).

Агент не привязан к одному языку: стек проекта определяется автоматически по маркерным файлам (`composer.json`, `package.json`, `pyproject.toml`, `go.mod`, …), команды проверки синтаксиса берутся из правил автолинта, а роль («PHP-разработчик», «Python-разработчик», …) задаётся профилем — флагом `--profile` или ключом `agent.profile`.

```
deepseek-agent/                 # = AGENT_HOME, определяется автоматически
├── agent.py                    # точка входа
├── requirements.txt            # зависимости: pip install -r requirements.txt
├── config.py                   # автопоиск конфигов, project_root, agent_home
├── agent.config.json           # настройки агента (путей в коде нет)
├── mcp_integration.py          # клиент MCP-серверов
├── skills_loader.py            # загрузка навыков
├── tools/
│   ├── __init__.py             # реестр инструментов и их схемы
│   ├── filesystem.py           # read/write/edit/list/grep + обзор структуры
│   ├── shell.py                # запуск команд (php -l, pytest)
│   ├── linter.py               # автолинт: проверка синтаксиса после правки
│   ├── loop_guard.py           # защита от зацикливания (повтор того же вызова)
│   ├── stack.py                # определение стека проекта по маркерным файлам
│   ├── git.py                  # git_status / git_diff / git_log (только чтение)
│   ├── web.py                  # web_search (DuckDuckGo) + fetch_url
│   ├── cache.py                # подсчёт и очистка кэша (.agent-cache)
│   └── snapshot.py             # автоснапшоты перед правкой
├── skills/                     # навыки агента (проектные подхватятся отдельно)
│   ├── code-quality/           # универсальные правила правок (любой язык)
│   ├── php-conventions/
│   ├── php-web/
│   ├── python-conventions/
│   ├── java-conventions/
│   ├── kotlin-conventions/
│   ├── android/
│   ├── swift-conventions/
│   ├── ios/
│   └── web-frontend/           # каждая — папка с SKILL.md
├── plugins/                    # (опционально) доп. модули агента
├── .agent-cache/               # служебное (в папке проекта, в git не попадает)
│   ├── backups/                # автоснапшоты правок, откат — :restore
│   ├── history.txt             # история интерактивных запросов
│   └── logs/session-*.log      # лог сессии (:log)
├── .agent.config.json          # ЛОКАЛЬНЫЙ оверрайд и секреты (в git не попадает)
├── .vscode/tasks.json          # готовые задачи VS Code для запуска агента
└── mcp_config.json             # MCP-серверы (пути — через ${project_root})
```

Рабочий проект (`PROJECT_ROOT`) — отдельная папка: он не обязан содержать файлы агента, но может добавить свои `skills/`, `mcp_config.json`, `plugins/` и `.agent.config.json` — всё это подхватится автоматически.

> В примерах ниже путь к папке агента обозначен как `<AGENT_HOME>` — подставьте свой (та папка, где лежит `agent.py`). Путь к рабочему проекту — `<PROJECT_ROOT>` (папка, открытая в VS Code). Реальных путей и ключей в репозитории нет и быть не должно.

---

## Содержание

- [Быстрый старт (5 минут)](#быстрый-старт-5-минут)
- [1. Требования](#1-требования)
- [2. Установка зависимостей](#2-установка-зависимостей)
- [3. Настройка API-ключа DeepSeek](#3-настройка-api-ключа-deepseek)
- [4. Запуск](#4-запуск)
- [5. Как агент находит проект и настройки](#5-как-агент-находит-проект-и-настройки)
- [6. Навыки (skills)](#6-навыки-skills)
- [7. Подключение MCP-серверов](#7-подключение-mcp-серверов)
- [8. Интеграция с VS Code](#8-интеграция-с-vs-code)
- [9. Все доступные флаги `agent.py`](#9-все-доступные-флаги-agentpy)
- [10. Частые проблемы](#10-частые-проблемы)
- [11. Лицензия](#11-лицензия)

---

## Быстрый старт (5 минут)

Агент — обычный Python-скрипт: устанавливать его не нужно, ничего собирать и
компилировать тоже. Достаточно один раз поставить зависимости и запускать
`agent.py` по его пути.

### Шаг 1. Проверьте Python (один раз)

```powershell
python --version
```

Нужен **Python 3.10 или новее**. Если команда не найдена — попробуйте `py --version`,
а если и это не сработало, установите Python с [python.org](https://www.python.org/downloads/),
отметив в установщике **Add python.exe to PATH** (подробнее — [раздел 1](#1-требования)).

### Шаг 2. Установите зависимости (один раз)

```powershell
python -m pip install -r "<AGENT_HOME>\requirements.txt"
```

Если файла под рукой нет — то же самое одной строкой:

```powershell
python -m pip install openai mcp rich prompt_toolkit
```

`openai` и `mcp` обязательны, `rich` и `prompt_toolkit` — только для красивого вывода
и истории команд (без них агент работает в упрощённом режиме, это не ошибка).
Подробности и решение проблем установки — [раздел 2](#2-установка-зависимостей).

### Шаг 3. Проверьте, что всё на месте (API-ключ ещё не нужен)

```powershell
python "<AGENT_HOME>\agent.py" --doctor
```

Вывод покажет `AGENT_HOME`, корень проекта, найденные конфиги, навыки, MCP-серверы,
доступные утилиты (`npx`, `php`, `python`), установленные пакеты и статус API-ключа.
Если в блоке «Пакеты Python» есть `✗ openai` или `✗ mcp` — вернитесь к шагу 2.

### Шаг 4. Задайте API-ключ (один раз)

```powershell
setx DEEPSEEK_API_KEY "sk-ваш-ключ"
```

Затем **закройте и откройте терминал заново** — `setx` применяется только к новым сессиям.
Альтернатива: положить ключ в `api.api_key` локального `.agent.config.json`
(подробнее — [раздел 3](#3-настройка-api-ключа-deepseek)).

### Шаг 5. Запустите агента в своём проекте

```powershell
cd "<PROJECT_ROOT>"                                  # корень проекта
python "<AGENT_HOME>\agent.py"                       # интерактивный режим
```

или разовая задача без диалога:

```powershell
python "<AGENT_HOME>\agent.py" -t "Проверь синтаксис PHP в src и исправь ошибки"
```

Корень проекта агент берёт из папки запуска (cwd), свою папку — из расположения
`agent.py`. Прописывать абсолютные пути в конфигах не нужно.

> Ещё короче: откройте папку **своего проекта** в VS Code (`File → Open Folder…`),
> нажмите `Terminal → New Terminal` и работайте в этом терминале — он стартует
> уже в корне проекта. Готовые задачи есть в `.vscode/tasks.json`
> ([раздел 8](#8-интеграция-с-vs-code)).

### Если что-то не сработало

| Симптом | Что делать |
|---|---|
| `python` не найден / открывается Microsoft Store | [раздел 1](#1-требования) |
| Ошибка при `pip install` | [раздел 2.5](#25-если-установка-не-проходит) |
| `ERROR: переменная окружения DEEPSEEK_API_KEY не установлена` | [раздел 3](#3-настройка-api-ключа-deepseek) |
| Агент работает не с тем проектом | [раздел 5](#5-как-агент-находит-проект-и-настройки) |
| Прочее | [раздел 10](#10-частые-проблемы) |

### Интерактивный режим

Запускать из терминала, открытого на папке **вашего проекта** (см. [раздел 4.3](#43-интерактивный-режим)):

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
| `:tools` | Список инструментов (веб и git — только если применимы) |
| `:lint [файл]` | Автолинт вручную: `:lint путь/к/файлу` — проверить файл; без аргумента — показать настроенные проверки |
| `:skills` | Загруженные навыки (проект + агент) |
| `:profile [имя]` | Показать активный профиль или переключить (`:profile php`, `:profile auto`) |
| `:profiles` | Список профилей (ролей) агента и их навыков |
| `:mcp` | Статус MCP-серверов |
| `:snapshots` | Список автоснапшотов правок |
| `:restore` | Откатить последний снапшот |
| `:config` | `agent_home`, `project_root`, прочитанные конфиги, текущие настройки |
| `:auto` | Вкл/выкл подтверждения |
| `:project` | Показать корень проекта |
| `:cache` | Объём кэша (снапшоты, логи, история ввода) и очистка по подтверждению |
| `:cache clear` | Очистить кэш сразу, без вопроса |
| `:log` | Путь к логу текущей сессии |
| `:doctor` | Диагностика (config, skills, mcp, снапшоты, утилиты) |
| `:exit` | Выход (также `exit`, `quit`, `:q`) |

### Инструменты агента

Файловые и shell:

| Инструмент | Назначение |
|---|---|
| `read_file`, `read_range` | Чтение файла целиком / диапазона строк |
| `write_file`, `edit_file` | Запись файла / точечная замена (`replace_all=true` — все вхождения) |
| `list_dir`, `grep` | Список файлов / поиск по regex (с фильтром по расширению) |
| `run_shell` | Команды (`php -l`, `node --check`, `pytest`); таймаут — `tools.shell_timeout` |

Git (только чтение, коммиты — за человеком):

| Инструмент | Назначение |
|---|---|
| `git_status` | Ветка и изменённые файлы |
| `git_diff` | Дифф (опционально `path`, `staged`) |
| `git_log` | Последние коммиты одной строкой |

Веб (без API-ключей, `tools.web.enabled`):

| Инструмент | Назначение |
|---|---|
| `web_search` | Поиск через DuckDuckGo, возвращает заголовки + URL + сниппеты |
| `fetch_url` | Скачать страницу и получить текст (HTML → plain text) |

Веб-инструменты запрашивают только публичные адреса: localhost и приватные IP
блокируются (и при загрузке, и при редиректах), ответ ограничивается по длине.

### Автолинт синтаксиса

После каждой правки (`write_file` / `edit_file`) агент сам запускает проверку
синтаксиса по правилам из конфига и добавляет её результат к ответу инструмента.
Модели не нужно «не забыть проверить» — проверка детерминированная.

- правила задаются в `agent.config.json` (секция `lint`): расширение → команда,
  в команду подставляется `{file}` (путь в кавычках). Если правило не подходит
  или утилиты нет в PATH, шаг молча пропускается;
- проверку можно запустить вручную: `:lint путь/к/файлу`, а `:lint` без
  аргумента покажет список настроенных проверок;
- примеры команд проверки в системном промпте **генерируются из этих же правил**,
  поэтому в проекте на Python не появятся примеры с `php -l`, и наоборот;
- отключить: `"lint": { "enabled": false }`, таймаут — `lint.timeout`.

### Стек проекта

При старте агент определяет стек по маркерным файлам (`composer.json`,
`package.json` + `tsconfig.json`, `pyproject.toml` / `requirements.txt`,
`go.mod`, `Cargo.toml`, `Gemfile`, `pom.xml`, `build.gradle(.kts)`,
`AndroidManifest.xml`, `Package.swift`, `*.xcodeproj`, …) и показывает его в
`--doctor` и `:config` (например, `Python (FastAPI)`, `PHP (Laravel)`,
`Android (Kotlin)` или `iOS (Swift)`). По этому же
определению подбираются навыки (см. `applies_to` в [разделе 6](#6-навыки-skills)),
если профиль не задан явно.

### Профиль (роль) агента

Профиль привязывает агента к конкретному языку: грузятся только его навыки,
и правила другого стека в промпт не попадают — агент работает «как PHP-разработчик»
или «как Python-разработчик» независимо от того, что ещё лежит в проекте.

```powershell
python "<AGENT_HOME>\agent.py" --list-profiles            # какие профили есть
python "<AGENT_HOME>\agent.py" --profile php              # запуск в роли PHP-разработчика
python "<AGENT_HOME>\agent.py" --profile python           # ...или Python-разработчика
```

Внутри сессии: `:profile` — показать активный, `:profile php` — переключить
(промпт пересобирается на ходу), `:profile auto` — вернуться к автоопределению
по стеку, `:profiles` — список профилей.

Постоянно — ключом в конфиге:

```json
{ "agent": { "profile": "php" } }
```

Профили по умолчанию: `php`, `python`, `frontend`, `java`, `kotlin`, `swift`
(плюс `""` = авто по стеку).
Свои добавляются секцией `profiles` в `agent.config.json` — **код агента менять
не нужно**, поэтому расширение на любой другой язык сводится к одному JSON-блоку
и папке навыка:

```json
{
  "profiles": {
    "go": {
      "description": "Go-разработчик",
      "skills": ["code-quality", "go-conventions"],
      "instructions": ["Идиоматичный Go: ошибки возвращаем явно, без panic()."]
    }
  }
}
```

Здесь `skills` — имена папок в `skills/`, то есть для `go` понадобится
`skills/go-conventions/SKILL.md` ([раздел 6.2](#62-встроенные-навыки-агента)).
Ключи `description`/`skills`/`instructions` необязательны, но `skills` и есть
то, что «инициализирует нужный навык». Если навыка с таким именем нет, в `:skills`
будет видно, что загрузилось, а `--doctor` покажет выбранный профиль и его список.

### Лимит шагов и защита от зацикливания

По умолчанию лимита шагов нет (`agent.max_steps = 0`): задача не обрывается
на середине из-за счётчика. Вместо этого работает loop-guard — защита по
существу, а не по количеству шагов:

- запоминается подпись вызова: инструмент + аргументы + результат;
- если **одно и то же действие повторяется подряд** `agent.loop_guard.repeat_limit`
  раз (по умолчанию 3) с тем же результатом, в диалог добавляется предупреждение
  «смени подход»;
- если после предупреждения цикл продолжается — задача останавливается с
  понятным сообщением (что повторялось), а не молчаливым «лимит шагов».

```json
{ "agent": { "max_steps": 0, "loop_guard": { "enabled": true, "repeat_limit": 3 } } }
```

Если нужен жёсткий предел на всякий случай — поставьте `max_steps` > 0;
`loop_guard.enabled = false` (или `repeat_limit: 0`) отключает защиту совсем.

### Кэш проекта (`.agent-cache`)

Кэш — служебные файлы агента внутри проекта: снапшоты правок
(`.agent-cache/backups`), логи сессий (`.agent-cache/logs`) и история ввода
(`.agent-cache/history.txt`). В git он не попадает, но со временем разрастается:
сотни снапшотов и логов замедляют поиск по проекту и могут случайно попасть
в контекст модели при чтении файлов.

Что делает агент:

- при запуске **интерактивного** режима спрашивает: `Очистить кэш перед началом работы?`
  — `Enter`/`n` оставляют всё как есть, `y` очищает (в разовом режиме `-t` вопрос не задаётся);
- ничего не удаляет молча: очистка всегда по ответу `y` или явной команде/флагу;
- вопрос отключается флагом `--no-cache-ask` или ключом
  `"cache": { "ask_on_start": false }` в `agent.config.json`.

Команды и флаги:

```powershell
:cache                                                # объём кэша + вопрос на очистку
:cache clear                                          # очистить сразу, без вопроса
python "<AGENT_HOME>\agent.py" --clear-cache          # очистить перед запуском
python "<AGENT_HOME>\agent.py" --clear-cache --doctor # очистить и показать диагностику
```

Очистка удаляет только `.agent-cache` (снапшоты, логи, историю ввода) и никогда
не трогает файлы проекта. После неё `:restore` не сможет откатить правки, чьи
снапшоты были удалены.

### Дополнительные зависимости для UI

`rich` и `prompt_toolkit` не обязательны: без них агент работает, но без цветного
вывода, спиннера, подсветки и истории команд. Ставятся вместе с остальным
(см. [раздел 2](#2-установка-зависимостей)):

```powershell
python -m pip install rich prompt_toolkit
```


---

## 1. Требования

Что реально нужно, а что — только для дополнительных возможностей:

| Компонент | Обязателен? | Зачем | Как проверить |
|---|---|---|---|
| **Windows 10/11** | да (среда описана для Windows) | команды в README — для PowerShell | — |
| **Python 3.10+** | да | MCP SDK не работает на 3.9 и ниже | `python --version` |
| **Node.js** | нет | только если подключаете MCP-серверы через `npx` (по умолчанию — filesystem) | `node --version` |
| **uv / uvx** | нет | только для MCP-серверов через `uvx` (например `mcp-server-fetch`) | `uvx --version` |
| **PHP** | нет | нужен, только если вы проверяете PHP-код (`php -l`) | `php -v` |
| **git** | нет | инструменты `git_status`/`git_diff`/`git_log` (если проект под git) | `git --version` |

```powershell
python --version
node --version
```

`python` не найден, открывается Microsoft Store или версия ниже 3.10:

1. Установите Python с [python.org](https://www.python.org/downloads/) (3.10 или новее).
2. В установщике обязательно отметьте **Add python.exe to PATH**.
3. Закройте и снова откройте терминал, проверьте `python --version`.

Если `python` всё равно не находится, попробуйте `py --version` (лаунчер Windows) — тогда
в командах ниже вместо `python` используйте `py`. Быстрая проверка всех компонентов
сразу: `python "<AGENT_HOME>\agent.py" --doctor`.

---

## 2. Установка зависимостей

Зависимостей всего четыре, и две из них необязательны:

| Пакет | Обязателен? | Что даёт |
|---|---|---|
| `openai` | **да** | клиент DeepSeek API (совместим с OpenAI) |
| `mcp` | **да** | подключение внешних MCP-серверов инструментов |
| `rich` | нет | цветной вывод, markdown, спиннер |
| `prompt_toolkit` | нет | удобное поле ввода и история команд (стрелка вверх) |

Без `rich` и `prompt_toolkit` агент запускается и работает — просто в упрощённом виде.

### 2.1. Установка одной командой

```powershell
python -m pip install -r "<AGENT_HOME>\requirements.txt"
```

или тем же списком вручную:

```powershell
python -m pip install openai mcp rich prompt_toolkit
```

Если репозиторий открыт в VS Code, путь короче: `python -m pip install -r requirements.txt`.

### 2.2. (Рекомендуется) Виртуальное окружение

Ставить пакеты можно и глобально — этого достаточно для работы. Но если не хочется
смешивать с другими проектами:

```powershell
python -m venv "<AGENT_HOME>\.venv"                  # создать один раз
"<AGENT_HOME>\.venv\Scripts\Activate.ps1"            # активировать в текущем терминале
python -m pip install -r "<AGENT_HOME>\requirements.txt"
```

Признак активированного окружения — `(.venv)` в начале строки приглашения. Тогда
`python` внутри терминала — это Python из окружения, и агент запускается как обычно.

Если PowerShell запрещает запуск `Activate.ps1` («выполнение сценариев отключено»),
разрешите его для текущего окна терминала:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Альтернатива: активировать через cmd (`<AGENT_HOME>\.venv\Scripts\activate.bat`)
или просто запускать агент из venv-интерпретатора напрямую:
`"<AGENT_HOME>\.venv\Scripts\python.exe" "<AGENT_HOME>\agent.py"`.

### 2.3. Проверка установки

```powershell
python -c "import importlib.util as u; print({m: bool(u.find_spec(m)) for m in ('openai','mcp','rich','prompt_toolkit')})"
```

Ожидаемый результат — все четыре значения `True`:

```text
{'openai': True, 'mcp': True, 'rich': True, 'prompt_toolkit': True}
```

Если `openai` или `mcp` равны `False` — установка не прошла, смотрите
[2.5](#25-если-установка-не-проходит). Ту же проверку (в удобном виде) делает
`python "<AGENT_HOME>\agent.py" --doctor` — блок «Пакеты Python».

### 2.4. Если pip не находит пакеты (зеркало)

Обычно `python -m pip install ...` работает с публичного PyPI как есть. Если у вас
настроено региональное зеркало (например Tsinghua TUNA) и свежие версии `mcp` там
отсутствуют, укажите рабочее зеркало:

```powershell
python -m pip install openai mcp rich prompt_toolkit -i https://mirrors.aliyun.com/pypi/simple/
```

Чтобы не повторять `-i` каждый раз, добавьте зеркала как резервные индексы:

```powershell
python -m pip config set global.extra-index-url "https://mirrors.aliyun.com/pypi/simple/ https://mirrors.cloud.tencent.com/pypi/simple/"
```

После этого обычный `python -m pip install <пакет>` будет искать пакет и в резервном источнике.

### 2.5. Если установка не проходит

- Обновите pip: `python -m pip install --upgrade pip`
- Очистите кэш: `python -m pip cache purge`
- Попробуйте другое зеркало: `python -m pip install mcp -i https://mirrors.cloud.tencent.com/pypi/simple/`
- Убедитесь, что вы ставите в нужный Python: `python -m pip -V` покажет и версию pip, и путь к интерпретатору
- Проверьте версию Python: `python --version` (нужна 3.10+)
- Если пакеты видны только в глобальном Python, а агент запускается из venv (или наоборот) — установите пакеты в тот же интерпретатор, которым запускаете `agent.py`
- Корпоративный прокси/файрвол: добавьте `--proxy http://user:pass@host:port` или попросите доступ к `pypi.org`

### 2.6. Опционально: MCP CLI-инструменты

Нужны, только если планируете отлаживать собственные MCP-серверы
(`mcp dev`, `mcp run`):

```powershell
python -m pip install "mcp[cli]"
```

---

## 3. Настройка API-ключа DeepSeek

Ключ берётся из переменной окружения (имя задаётся в `api.api_key_env`, по умолчанию `DEEPSEEK_API_KEY`), а если её нет — из `api.api_key` в **локальном** `.agent.config.json` (он не коммитится, см. `.gitignore`).

> ⚠️ Никогда не публикуйте реальный ключ: `.agent.config.json`, `agent.config.local.json`, `mcp_config.local.json` и `.mcp.json` уже в `.gitignore`. Если ключ всё-таки попал в git или в публичный файл — сразу отзовите его в консоли DeepSeek и выпустите новый.

Рекомендуемый способ — переменная окружения, её достаточно задать **один раз**:

```powershell
setx DEEPSEEK_API_KEY "sk-ваш-ключ"
```

**Перезапустите PowerShell** (или откройте новое окно) — переменные, установленные через `setx`, применяются к новым сессиям.

Проверка, что переменная видна в новом терминале:

```powershell
echo $env:DEEPSEEK_API_KEY
```

Проверка, что ключ принят API (запускать из папки агента; ответ модели = ключ рабочий):

```powershell
python -c "import config; from openai import OpenAI; c=OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL); print(c.chat.completions.create(model=config.MODEL, messages=[{'role':'user','content':'ping'}]).choices[0].message.content)"
```

Без ключа в окружении агент возьмёт `api.api_key` из локального `.agent.config.json` (в репозиторий его не добавляйте).
Состояние ключа всегда видно в `python "<AGENT_HOME>\agent.py" --doctor` и по `:config`.

---

## 4. Запуск

Главное правило: **агент запускается из папки проекта** (или ей указывают корень
флагом `-p`). Тогда:

- `PROJECT_ROOT` = папка, откуда запущен агент (cwd);
- `AGENT_HOME` = папка, где лежит `agent.py` (определяется автоматически из его расположения).

Два равнозначных варианта:

```powershell
# A. Терминал открыт в папке проекта, агент вызывается по своему пути
cd "<PROJECT_ROOT>"
python "<AGENT_HOME>\agent.py"

# B. VS Code открыт на папке проекта: Terminal → New Terminal
#    (терминал стартует в корне проекта) и та же команда
python "<AGENT_HOME>\agent.py"
```

Если сомневаетесь, что корень определился верно — `python "<AGENT_HOME>\agent.py" --doctor`
покажет `AGENT_HOME`, `PROJECT_ROOT` и `cwd`.

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
Если в проекте есть кэш (`.agent-cache`), при старте агент спросит, очищать ли его —
`Enter`/`n` оставляют как есть, `y` очищает (см. [Кэш проекта](#кэш-проекта-agent-cache)).

### 4.4. Без подтверждений (для автоматизации)

```powershell
python "<AGENT_HOME>\agent.py" -t "Запусти php -l на всех файлах src" --yes
```

Флаги `--no-confirm` / `--yes` отключают запросы подтверждения для `write_file`, `edit_file` и `run_shell`.

### 4.5. Проверка окружения без API-запроса

```powershell
python "<AGENT_HOME>\agent.py" --doctor
```

Показывает пути (`AGENT_HOME`, `PROJECT_ROOT`, `cwd`), прочитанные конфиги, текущие
настройки, найденные навыки, MCP-серверы, снапшоты, доступные утилиты (`npx`, `php`,
`python`), установленные пакеты и статус API-ключа. Ключ для этой команды не нужен —
удобно запускать сразу после установки. То же самое изнутри сессии — команда `:doctor`.

---

## 5. Как агент находит проект и настройки

Этот раздел нужен, только если проект лежит не там, откуда вы запускаете агента,
или если хотите изменить настройки. В простом случае (`cd <PROJECT_ROOT>` +
`python "<AGENT_HOME>\agent.py"`) ничего настраивать не требуется.

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
  "snapshots": { "max_backups": 50 },
  "cache": { "ask_on_start": true },
  "agent": {
    "max_steps": 0,
    "api_retries": 3,
    "language": "русском",
    "profile": "",
    "loop_guard": { "enabled": true, "repeat_limit": 3 },
    "instructions": []
  },
  "profiles": {
    "php":      { "description": "PHP-разработчик (веб-приложения)", "skills": ["code-quality", "php-conventions", "php-web"] },
    "python":   { "description": "Python-разработчик", "skills": ["code-quality", "python-conventions"] },
    "frontend": { "description": "Фронтенд-разработчик (HTML/CSS/JS/TS)", "skills": ["code-quality", "web-frontend"] },
    "java":     { "description": "Java-разработчик (JVM, Spring, Maven/Gradle)", "skills": ["code-quality", "java-conventions"] },
    "kotlin":   { "description": "Kotlin/Android-разработчик", "skills": ["code-quality", "kotlin-conventions", "android"] },
    "swift":    { "description": "Swift/iOS-разработчик (Apple-платформы)", "skills": ["code-quality", "swift-conventions", "ios"] }
  },
  "lint": {
    "enabled": true,
    "timeout": 30,
    "rules": [
      { "ext": [".php", ".phtml"], "command": "php -l {file}", "label": "php -l" },
      { "ext": [".js", ".mjs", ".cjs"], "command": "node --check {file}", "label": "node --check" },
      { "ext": [".py"], "command": "python -m py_compile {file}", "label": "python -m py_compile" }
    ]
  },
  "tools": {
    "shell_timeout": 60,
    "web": { "enabled": true, "timeout": 20, "max_chars": 20000, "results": 5 }
  }
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
| `cache.ask_on_start` | Спрашивать при старте REPL, очищать ли кэш (`.agent-cache`) |
| `agent.max_steps` | Максимум шагов модели на одну задачу. `0` (по умолчанию) = без ограничений |
| `agent.loop_guard.enabled` | Ловить зацикливание: одинаковый вызов инструмента с тем же результатом подряд |
| `agent.loop_guard.repeat_limit` | Сколько таких повторов подряд считать циклом (`0` = выключить защиту) |
| `agent.profile` | Профиль (роль) агента: `php`, `python`, `frontend`, `java`, `kotlin`, `swift` или свой из `profiles`. Пусто = авто по стеку |
| `agent.api_retries` | Сколько раз повторять запрос к API при сетевой ошибке/429 |
| `agent.language` | Язык ответов агента (подставляется в системный промпт) |
| `agent.instructions` | Доп. правила проекта: строка или список строк (попадают в промпт) |
| `profiles.<имя>` | Свой профиль: `{"description": ..., "skills": [...], "instructions": [...]}` |
| `lint.enabled` | Автолинт: проверять синтаксис сразу после `write_file`/`edit_file` |
| `lint.timeout` | Таймаут одной проверки, секунды |
| `lint.rules` | Правила: `{"ext": [".php"], "command": "php -l {file}", "label": "php -l"}`. `{file}` — путь к файлу |
| `tools.shell_timeout` | Таймаут shell-команд, секунды |
| `tools.web.enabled` | Включить `web_search` / `fetch_url` (выключено — инструменты скрыты от модели) |
| `tools.web.timeout` | Таймаут одного HTTP-запроса |
| `tools.web.max_chars` | Лимит символов страницы, отдаваемых модели |
| `tools.web.results` | Сколько результатов поиска возвращать по умолчанию |
| `api.*` | Ключ (env предпочтительнее), модель, base_url, temperature, лимит контекста. Секреты — только в локальном `.agent.config.json` |

Служебные файлы в проекте: `.agent-cache/backups/` (снапшоты),
`.agent-cache/history.txt` (история REPL), `.agent-cache/logs/session-*.log`
(лог сессии: запросы, вызовы инструментов, ошибки; путь — команда `:log`).
Всё это чистится командой `:cache` / `:cache clear` или флагом `--clear-cache`,
а вопрос об очистке при старте управляется ключом `cache.ask_on_start`.

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

Проверка настроек: `python "<AGENT_HOME>\agent.py" --doctor` (или `:config` внутри сессии) покажет `agent_home`, `project_root`, `cwd`, список прочитанных конфигов и все действующие значения.

---

## 6. Навыки (skills)

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

### 6.1. Отбор навыков по стеку (`applies_to`)

Необязательное поле `applies_to` в front-matter ограничивает навык определённым стеком: он подключится, только если стек проекта (см. раздел выше) содержит хотя бы один из тегов.

```markdown
---
name: python-conventions
description: Правила для Python-кода
applies_to: [python, django, flask, fastapi]
---
```

Без `applies_to` навык подключается всегда. Если стек определить не удалось, загружаются все навыки (агент не остаётся без правил в незнакомом проекте). Так проект на Python не получает PHP-правила, а PHP-проект — Python-правила. Что реально загрузилось, видно по `:skills`, а определённый стек — в `--doctor` / `:config`.

Если задан **профиль** (`agent.profile` / `--profile` / `:profile`), он важнее автоопределения: грузятся ровно перечисленные в нём навыки, а `applies_to` не учитывается — так агент становится «PHP-разработчиком» или «Python-разработчиком» независимо от содержимого проекта.

### 6.2. Встроенные навыки агента

В `<AGENT_HOME>/skills/` лежат навыки по умолчанию (проектные с тем же именем их перекрывают):

| Навык | Когда подключается |
|---|---|
| `code-quality` | Всегда: минимальный дифф, чтение перед правкой, без отладочного кода, без секретов в коде |
| `php-conventions` | Проекты на PHP: `declare(strict_types=1)`, PSR-12/PSR-4, проверка `php -l` |
| `php-web` | Веб на PHP (Laravel, Symfony, Yii, CakePHP): PDO/prepared statements, экранирование вывода, CSRF, `password_hash()` |
| `python-conventions` | Проекты на Python (Django, Flask, FastAPI): PEP 8, типизация, `logging` вместо `print`, ресурсы через `with` |
| `java-conventions` | Проекты на Java (JVM, Spring, Maven/Gradle): именование, `equals` вместо `==`, try-with-resources, `record`/`var` в Java 17+ |
| `kotlin-conventions` | Проекты на Kotlin (JVM/Android): `val` вместо `var`, null-safety без `!!`, корутины без `GlobalScope`, scope-функции |
| `android` | Приложения под Android: `ViewModel`/репозитории, ресурсы вместо хардкода, разрешения в рантайме, R8/`@Keep` |
| `swift-conventions` | Проекты на Swift (Apple): `let`/`struct`, без force unwrap, `async/await` и `actor`, `os.Logger` |
| `ios` | Приложения под iOS (UIKit/SwiftUI): разделение UI и логики, SwiftUI-состояние, локализация, Keychain |
| `web-frontend` | HTML/CSS/JS/TS (React, Vue, Svelte, Next, Nuxt, Angular): семантика и доступность, Flexbox/Grid, mobile-first |

Свои навыки можно положить в `<PROJECT_ROOT>/skills/` — они приоритетнее встроенных.

---

## 7. Подключение MCP-серверов

MCP (Model Context Protocol) позволяет агенту использовать инструменты внешних серверов: filesystem, git, sqlite, memory и другие — без написания кода под каждый.

### 7.1. Создайте `mcp_config.json` в корне проекта или рядом с агентом

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

### 7.2. Запустите агента

При старте он автоматически найдёт `mcp_config.json` (путь — `paths.mcp_config`) и подключит серверы:

```
[MCP] подключён: filesystem (11 инструментов)
[MCP] подключён: git (9 инструментов)
MCP: 20 инструментов из 2 серверов (mcp_config.json)
```

Число инструментов и список найденных конфигов у вас будут свои; статус в любой момент виден по `:mcp`.

Все MCP-инструменты доступны модели наравне с обычными (`read_file`, `grep`, `run_shell` и т.д.).

### 7.3. Безопасность

- MCP-инструменты, изменяющие файлы или выполняющие команды, проходят через `confirm()`. Отключается флагом `--yes` — используйте только в доверенных сценариях.
- Сервер `@modelcontextprotocol/server-filesystem` принимает список разрешённых директорий в `args`. Не давайте ему корень диска (например `C:/`) — только папку проекта.
- Никогда не коммитьте секреты: `api_key` и локальные оверрайды держите в `.agent.config.json` (он в `.gitignore`).

### 7.4. Веб-доступ

Встроенные `web_search` и `fetch_url` не требуют ключей и зависимостей
(только стандартная библиотека Python). Управление — секция `tools.web`:

```json
{ "tools": { "web": { "enabled": true, "timeout": 20,
                      "max_chars": 20000, "results": 5 } } }
```

Выключить совсем: `"web": { "enabled": false }` — тогда инструменты просто
не показываются модели.

Если нужен более «тяжёлый» поиск (Brave/Google) или чтение JS-страниц,
подключите MCP-сервер вместо правки кода:

```json
{
  "mcpServers": {
    "fetch": { "enabled": true, "command": "uvx", "args": ["mcp-server-fetch"] },
    "search": {
      "enabled": false,
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": { "BRAVE_API_KEY": "${env:BRAVE_API_KEY}" }
    }
  }
}
```

`mcp-server-fetch` требует `uv`/`uvx`, `brave-search` — ключ Brave API
(бесплатный тариф есть). Агент сам подхватит их при старте.

---

## 8. Интеграция с VS Code

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
      "args": ["${workspaceFolder}/agent.py", "--doctor"],
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

## 9. Все доступные флаги `agent.py`

| Флаг | Описание |
|---|---|
| `-p, --project-root` | Корень проекта. По умолчанию — папка запуска (cwd) |
| `-t, --task` | Задача для агента. Если не указана — интерактивный режим |
| `--profile` | Профиль (роль) агента: `php`, `python`, `frontend`, `java`, `kotlin`, `swift` или свой из `profiles` |
| `--list-profiles` | Показать доступные профили и выйти (API-ключ не нужен) |
| `--doctor` | Показать диагностику окружения и выйти (API-ключ не нужен) |
| `--clear-cache` | Очистить кэш проекта (`.agent-cache`) перед запуском, без вопросов |
| `--no-cache-ask` | Не спрашивать при старте про очистку кэша |
| `--no-confirm` | Не спрашивать подтверждения для опасных операций |
| `-y, --yes` | Алиас для `--no-confirm` |
| `--show-tokens` | Показать статистику токенов после разовой задачи |
| `-h, --help` | Краткая справка по флагам |

Примеры:

```powershell
python "<AGENT_HOME>\agent.py" --doctor                                # проверить установку
python "<AGENT_HOME>\agent.py"                                         # диалог (REPL)
python "<AGENT_HOME>\agent.py" --clear-cache                           # почистить и работать
python "<AGENT_HOME>\agent.py" -t "Найди все TODO в src"               # разовая задача
python "<AGENT_HOME>\agent.py" -p "D:/work/site" -t "Запусти php -l"   # другой проект
python "<AGENT_HOME>\agent.py" -t "Исправь ошибки php -l в src" -y     # без подтверждений
python "<AGENT_HOME>\agent.py" --profile php                           # роль PHP-разработчика
python "<AGENT_HOME>\agent.py" --list-profiles                         # какие роли есть
```

---

## 10. Частые проблемы

**`python` не найден, открывается Microsoft Store или найден не тот Python**
Установите Python 3.10+ с [python.org](https://www.python.org/downloads/) и отметьте
**Add python.exe to PATH**; затем откройте новый терминал. Проверить, какой именно
интерпретатор запускается: `python -c "import sys; print(sys.executable)"`.
Пакеты должны стоять в **том же** интерпретаторе: `python -m pip -V`.
Запасной вариант — лаунчер `py` (`py --version`, `py -m pip install ...`).
Отключить заглушку Microsoft Store: `Параметры → Приложения → Дополнительные параметры
приложения → Псевдонимы выполнения приложения` → выключить `python.exe` / `python3.exe`.

**`ERROR: Could not find a version that satisfies the requirement mcp`**
Обычно это региональное зеркало pip без свежих пакетов. Укажите рабочее зеркало:
`python -m pip install mcp -i https://mirrors.aliyun.com/pypi/simple/`.
Если не помогает — проверьте версию Python (нужна 3.10+) и что вы ставите в тот же
интерпретатор, которым запускаете агента.

**`pip` ставит пакеты «не туда» / агент не видит `openai`, `mcp`**
Пакеты и агент должны использовать один интерпретатор. Проверьте:
`python -m pip -V` (путь к Python) и `python -c "import sys; print(sys.executable)"`.
Если работаете в venv — активируйте его в том терминале, откуда запускаете `agent.py`
(признак: `(.venv)` в приглашении), затем повторите установку.

**`ERROR: переменная окружения DEEPSEEK_API_KEY не установлена`**
Выполните `setx DEEPSEEK_API_KEY "sk-..."` и **перезапустите терминал** — либо впишите ключ в `api.api_key` в локальном `.agent.config.json` (не в отслеживаемый git `agent.config.json`). Статус ключа видно в `--doctor`.

**Консоль показывает «кракозябры» вместо русских букв**
Агент сам переключает вывод в UTF-8. Если эмодзи/стрелки ломаются, запускайте из
Windows Terminal / PowerShell 7; для очень старых консолей: `chcp 65001`.

**[config] ... JSONDecodeError при старте**
Сломан один из конфигов (`agent.config.json` / `.agent.config.json`) — лишняя запятая, неэкранированные обратные слэши. Абсолютный путь в JSON указывайте через прямые слэши (`<диск>:/путь/к/проекту`). Имя битого файла видно в сообщении.

**[MCP] <сервер>: не раскрыта подстановка ${project_root}**
Сервер запускается из конфига, где `${project_root}` не во что раскрыть. Запустите агента из папки проекта (или укажите корень через `-p`), чтобы подстановка `${project_root}` раскрылась.

**Агент работает не с тем проектом**
Корень = папка запуска (cwd). Типичная причина — агент запущен из **своей** папки, а не из папки проекта. Проверьте `--doctor` / `:config` (строки `project_root` и `cwd`) — при необходимости задайте `-p <PROJECT_ROOT>`, переменную `DEEPSEEK_PROJECT_ROOT` или `.agent.config.json` в проекте.

**MCP-сервер не подключается**
Проверьте, что `npx` или `uvx` доступны в PATH (`npx --version`). Попробуйте запустить команду сервера вручную из PowerShell — увидите реальную ошибку. Также убедитесь, что `"enabled"` не выставлен в `false`.

**Агент пишет «Путь вне проекта запрещён»**
Все пути в tool calls приводятся к корню проекта: агент намеренно не выходит за пределы песочницы. Проверьте корень командой `:project` / `:config`.

**Долгий первый запуск MCP**
Первый `npx -y @modelcontextprotocol/server-filesystem` скачивает пакет из npm — это может занять 20–30 секунд. Второй запуск будет быстрым.

**Агент зациклился: одно и то же действие повторяется**
Сработал loop-guard: вызов инструмента с теми же аргументами и результатом
повторился `agent.loop_guard.repeat_limit` раз подряд (по умолчанию 3). Сначала
агент получает предупреждение «смени подход», а при продолжении цикла задача
останавливается с указанием, что именно повторялось. Уточните задачу (часто
помогает сказать, какой файл и что именно поправить) или ослабьте защиту:
`"loop_guard": { "repeat_limit": 5 }`, `"enabled": false` — выключить.

**«Достигнут лимит шагов»**
Лимит по умолчанию снят (`agent.max_steps = 0`), так что это сообщение означает,
что в конфиге стоит своё число. Увеличьте его или верните `0` — от зацикливания
защищает loop-guard (см. выше).

**`ERROR: команда не завершилась за 60 секунд`**
Сработал таймаут `run_shell` (`tools.shell_timeout`). Увеличьте его в `agent.config.json`
или попросите агента запускать более короткие команды.

**`fetch_url`: «запрос отклонён (SSRF-защита)»**
Так и задумано: агент читает только публичные адреса, `localhost` и приватные сети
(`127.0.0.1`, `10.x`, `192.168.x`) заблокированы. Для локальных сервисов используйте
`run_shell` (`curl http://127.0.0.1:8124`).

**`web_search` вернул «Совпадений не найдено»**
DuckDuckGo ограничивает частоту запросов. Подождите или откройте конкретный URL
через `fetch_url`; для «тяжёлого» поиска подключите MCP-сервер Brave
([раздел 7.4](#74-веб-доступ)).

**Накопилось много снапшотов/логов, поиск по проекту тормозит**
Почистите кэш: `:cache` (покажет объём и спросит), `:cache clear` (сразу) или
`python "<AGENT_HOME>\agent.py" --clear-cache`. Удаляются только `.agent-cache`
(снапшоты, логи, история ввода) — файлы проекта не трогаются.

**Вопрос про очистку кэша мешает / не нужен**
Отключите его: флаг `--no-cache-ask` или `"cache": { "ask_on_start": false }`
в `agent.config.json`. Ограничить число снапшотов можно ключом
`snapshots.max_backups`.

---

## 11. Лицензия

MIT — используйте, форкайте, адаптируйте под себя.