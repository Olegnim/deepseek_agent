# DeepSeek CLI Agent

CLI-агент на Python для написания и правки кода через DeepSeek API: читает файлы,
ищет по проекту, правит код, запускает тесты и линтеры — всё в терминале. Язык и
стек любые (PHP, Python, JS/TS, Java, Kotlin, Swift, веб). Работает на **Windows**,
**Linux** и **macOS**.

- **Инструменты, а не «скопируй файл в чат»** — чтение и точечная правка файлов,
  поиск по коду с выжимкой, shell, git, веб-поиск без ключей, изображения.
- **Автолинт** — синтаксис проверяется сразу после каждой правки.
- **Снапшоты** — любую правку можно откатить одной командой.
- **Навыки и профили** — правила проекта и роли (`php`, `python`, `frontend`, …).
- **Планирование** — крупная задача сначала описывается в `PLAN.md`, потом
  выполняется автопилотом.
- **MCP-серверы** и **VS Code** — агент открывает правленые файлы в редакторе.

> Примеры команд даны для Windows. На Linux/macOS замените `python` → `python3`,
> а `\` в путях → `/`.

## Установка

В примерах `<AGENT_HOME>` — папка агента (там, где лежит `agent.py`). Прописывать
её путь никуда не нужно: агент находит себя сам, а `<PROJECT_ROOT>` — папка вашего
проекта.

1. **Python 3.10 или новее** — [python.org](https://www.python.org/downloads/)
   (в установщике отметьте *Add python.exe to PATH*); на Debian/Ubuntu —
   `sudo apt install python3 python3-venv python3-pip`, на macOS — `brew install python3`.
2. **Зависимости:**

   ```powershell
   python -m pip install -r "<AGENT_HOME>\requirements.txt"
   ```

   `openai` и `mcp` обязательны, `rich` и `prompt_toolkit` — только для цветного
   вывода и истории команд. Если pip ставит пакеты не в тот интерпретатор или
   Ubuntu 24.04+ ругается на `externally-managed-environment` — работайте в
   виртуальном окружении:

   ```powershell
   python -m venv "<AGENT_HOME>\.venv"
   "<AGENT_HOME>\.venv\Scripts\Activate.ps1"
   python -m pip install -r "<AGENT_HOME>\requirements.txt"
   ```

   На Linux/macOS — `python3 -m venv "<AGENT_HOME>/.venv"` и
   `source "<AGENT_HOME>/.venv/bin/activate"`.

3. **API-ключ DeepSeek** — только в переменной окружения, затем перезапустите
   терминал:

   ```powershell
   setx DEEPSEEK_API_KEY "sk-ваш-ключ"
   ```

   ```bash
   export DEEPSEEK_API_KEY="sk-ваш-ключ"   # Linux/macOS
   ```

4. **Проверка установки** (API-ключ не нужен):

   ```powershell
   python "<AGENT_HOME>\agent.py" --doctor
   ```

   Покажет пути, найденные конфиги, навыки, MCP-серверы, утилиты и статус
   пакетов. Если в блоке «Пакеты Python» стоит `✗ openai` или `✗ mcp` — вернитесь
   к шагу 2.

## Запуск

Агент работает с проектом, **из папки которого вы его запустили**:

```powershell
cd "<PROJECT_ROOT>"
python "<AGENT_HOME>\agent.py"                                  # интерактивный режим
python "<AGENT_HOME>\agent.py" -t "Исправь ошибки PHP в src"    # разовая задача
```

**Не запускайте агент из его собственной папки** — иначе корнем проекта станет она
сама (тогда укажите `-p <PROJECT_ROOT>`).

### Флаги `agent.py`

| Флаг | Описание |
|---|---|
| `-p, --project-root` | Корень проекта (по умолчанию — папка запуска) |
| `-t, --task` | Разовая задача; без флага — интерактивный режим |
| `--profile <имя>` | Профиль (роль): `php`, `python`, `frontend`, `java`, `kotlin`, `swift`, `csharp`, `go`, `rust`, `ruby`, `cpp`, `devops` или свой |
| `--list-profiles` | Список профилей и выход (ключ не нужен) |
| `--doctor` | Диагностика окружения и выход (ключ не нужен) |
| `-y, --yes` / `--no-confirm` | Без запросов подтверждения (для автоматизации) |
| `--show-tokens` | Статистика токенов после разовой задачи |
| `--clear-cache` / `--no-cache-ask` | Очистить кэш перед стартом / не спрашивать про очистку |
| `-h, --help` | Справка |

## Команды в сессии

| Команда | Что делает |
|---|---|
| `:help` | Справка |
| `:clear` | Очистить историю диалога |
| `:doctor` / `:config` / `:project` | Диагностика / настройки / корень проекта |
| `:tools` | Список инструментов агента |
| `:lint [файл]` | Автолинт вручную; без аргумента — список правил |
| `:skills` / `:profile [имя]` / `:profiles` | Навыки / активный профиль и переключение / список профилей |
| `:think [on\|off\|low\|high\|max\|auto]` | Режим рассуждений |
| `:stream [on\|off\|auto]` | Стриминг ответа |
| `:plan` / `:plan on` / `:plan approve` / `:plan off\|auto` | Планирование (см. ниже) |
| `:snapshots` / `:restore` | Список снапшотов / откатить последний |
| `:cache` / `:cache clear` | Объём кэша / очистить |
| `:tokens` / `:context` / `:log` | Токены / размер контекста / путь к логу сессии |
| `:auto` | Вкл/выкл подтверждения |
| `:mcp` / `:vscode` / `:vscode start` | Статус MCP-серверов / моста VS Code / поднять мост |
| `:exit` | Выход (также `exit`, `quit`, `:q`) |

### Планирование

| Режим | Поведение |
|---|---|
| `auto` (по умолчанию) | Мелкую задачу агент делает сразу; для крупной задаёт один вопрос: «планировать или выполнить сразу?» |
| `:plan on` | Только план: пишется `PLAN.md`, правки файлов заблокированы |
| `:plan approve` | План утверждён: автопилот без подтверждений, шаги по порядку `depends_on` |
| `:plan off` | Без планирования, прежний режим подтверждений |

Задача в плане — это `ID`, `depends_on`, наблюдаемое поведение (какой командой
проверяется) и критерий приёмки; тесты пишутся до реализации. После каждого шага
агент гоняет линтер и узкие тесты и отмечает прогресс в `PLAN.md` (`- [x] ID`).

## Инструменты

| Инструмент | Назначение |
|---|---|
| `read_file`, `read_range` | Файл целиком / диапазон строк |
| `write_file`, `edit_file` | Запись файла / точечная замена (`replace_all=true` — все вхождения) |
| `list_dir`, `grep`, `search_code` | Список файлов / поиск по regex / поиск с контекстом и сводкой |
| `file_outline`, `read_symbol` | Карта символов файла / тело функции по имени |
| `diff_files`, `find_files`, `project_map` | Сравнение файлов / файлы по маске / структура проекта |
| `read_image` | Картинка или скриншот для модели (JPEG, PNG, GIF, WebP) |
| `run_shell` | Shell-команды (`php -l`, `node --check`, `pytest`), таймаут — `tools.shell_timeout` |
| `git_status`, `git_diff`, `git_log` | Состояние репозитория (только чтение) |
| `web_search`, `fetch_url` | Поиск (DuckDuckGo) и чтение страниц без API-ключей |
| `vscode_*` | Открыть файл в редакторе, показать в проводнике, дифф со снапшотом |

Большие результаты (pytest, сборка, `git log`, веб-страницы) не «съедают»
контекст: модель получает выжимку, а полный вывод лежит в
`.agent-cache/output/` — его можно прочитать точечно.

**Автолинт** после `write_file`/`edit_file` проверяет синтаксис по правилам секции
`lint` (`php -l`, `node --check`, `python -m py_compile`, `javac`, `kotlinc`,
`swiftc`); нет утилиты или правила — шаг пропускается. Отключается ключом
`"lint": { "enabled": false }`.

## Настройки

Всё лежит в `agent.config.json` рядом с агентом; локальные правки и секреты — в
`.agent.config.json` (в git не попадает). Самые нужные ключи:

| Ключ | Смысл |
|---|---|
| `api.api_key_env` / `api.model` | Имя переменной с ключом / модель |
| `api.thinking` / `api.reasoning_effort` | Рассуждения и их усилие (`low`/`high`/`max`) |
| `agent.profile` | Профиль (роль); пусто — авто по стеку |
| `agent.max_steps` | Лимит шагов модели на задачу (`0` — без лимита) |
| `agent.instructions` | Доп. правила проекта, попадают в промпт |
| `lint.enabled` / `lint.rules` | Автолинт и правила (`{file}` — путь к файлу) |
| `tools.shell_timeout` | Таймаут shell-команд, сек |
| `snapshots.max_backups` | Сколько снапшотов хранить |

Полный список, приоритет конфигов, подстановки `${project_root}` / `${env:VAR}`,
режимы API и vision — в [`docs/configuration.md`](docs/configuration.md).

Текущие значения в любой момент: `:config` или `--doctor`.

## Навыки и профили

**Навык** — папка с `SKILL.md`, содержимое которого подмешивается в системный
промпт:

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
- Не оставляй `var_dump` и `print_r` в коммитах.
```

Навыки проекта и агента объединяются, одноимённый проектный перекрывает
агентский. Встроенные: `code-quality` (всегда), `php-conventions`, `php-web`,
`python-conventions`, `java-conventions`, `kotlin-conventions`, `android`,
`swift-conventions`, `ios`, `web-frontend`.

**Профиль** привязывает агента к языку: грузятся только его навыки.
`--profile php`, в сессии — `:profile php`, постоянно — `"agent": { "profile": "php" }`.
Свой профиль добавляется секцией `profiles` в `agent.config.json`.

## MCP и VS Code

**MCP-серверы** подключаются файлом `mcp_config.json` в корне проекта или рядом с
агентом:

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

Абсолютные пути не нужны — используйте `${project_root}`. Статус — `:mcp`.
Подробности (roots/list, ограничения доступа) — в
[`docs/integrations.md`](docs/integrations.md).

**VS Code**: расширение из `vscode-extension/` поднимает локальный мост, и агент
открывает правленые файлы в новых вкладках, показывает их в проводнике и открывает
дифф со снапшотом. Интеграция необязательная: нет расширения или редактор закрыт
— агент работает как обычно. Установка и настройка — в
[`docs/integrations.md`](docs/integrations.md) и
[`vscode-extension/README.md`](vscode-extension/README.md).

## Если что-то не работает

- **`python` не найден / открывается Microsoft Store** — установите Python 3.10+
  с галкой *Add python.exe to PATH*; на macOS/Linux команды `python` обычно нет —
  используйте `python3`.
- **`No module named pytest`** — пакет стоит в другом интерпретаторе: сверьте
  `python -m pip -V` с `python -c "import sys; print(sys.executable)"`.
- **Ключ не найден** — задайте `DEEPSEEK_API_KEY` и перезапустите терминал.
- **Агент работает не с тем проектом** — корень = папка запуска; проверьте
  `:config` и задайте `-p`.
- **«кракозябры» в консоли** — используйте Windows Terminal / PowerShell 7.

Остальное (MCP, пути Windows, снапшоты, VS Code, таймауты) — в
[`docs/troubleshooting.md`](docs/troubleshooting.md).

## Разработка

Тесты: `python -m pip install -r requirements-dev.txt && python -m pytest`
(около 3 секунд, сеть и API не нужны). Что покрыто и как устроен код — в
[`docs/development.md`](docs/development.md).

## Лицензия

MIT — используйте, форкайте, адаптируйте под себя.
