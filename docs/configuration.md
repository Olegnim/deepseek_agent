# Настройки и пути

Всё настройки агента лежат в JSON-файлах и читаются слоями: проектный конфиг
перекрывает `agent.config.json` рядом с агентом, а тот — значения по умолчанию из
`config.py`.

| Файл | Что это |
|---|---|
| `agent.config.json` | Основные настройки (в git — шаблон без секретов) |
| `.agent.config.json` | Локальный оверрайд и секреты (в git не попадает) |
| `<PROJECT_ROOT>/.agent.config.json` | Настройки конкретного проекта |
| `mcp_config.json` / `.mcp.json` | MCP-серверы |
| `skills/<имя>/SKILL.md` | Навыки проекта |

## `AGENT_HOME` и `PROJECT_ROOT`

| Понятие | Как определяется |
|---|---|
| `AGENT_HOME` | Автоматически из расположения `agent.py`. Переопределяется переменной `DEEPSEEK_AGENT_HOME` |
| `PROJECT_ROOT` | Автоматически = папка запуска (cwd). Песочница: инструменты не выйдут за её пределы |

Приоритет `PROJECT_ROOT`: `-p` > `DEEPSEEK_PROJECT_ROOT` > `.agent.config.json` в
папке запуска > `agent.config.json` > cwd.

Общие ресурсы ищутся по цепочке «проект → папка агента» и объединяются: `skills/`,
`mcp_config.json` / `.mcp.json`, `plugins/`.

Всё проверяется одной командой: `--doctor` (или `:config` в сессии) — покажет
`agent_home`, `project_root`, `cwd`, список прочитанных конфигов и действующие
значения.

## Ключевые настройки

| Ключ | Смысл |
|---|---|
| `api.api_key_env` / `api.model` | Имя переменной с ключом / модель |
| `agent.profile` | Профиль (роль); пусто = авто по стеку |
| `agent.max_steps` | Лимит шагов модели на задачу; `0` = без лимита (защита от зацикливания — `loop_guard`) |
| `agent.instructions` | Доп. правила проекта (строка/список, попадают в промпт) |
| `agent.language` | Язык ответов агента (подставляется в промпт: «Отвечай кратко, на {language}») |
| `paths.project_root` | Пусто = папка запуска |
| `paths.mcp_config` / `paths.skills_dir` / `paths.backup_dir` | Пути к MCP-конфигам / навыкам / снапшотам |
| `paths.plugins_dirs` | Папки плагинов (`.py` с `register(api)`, доп. инструменты); пусто — плагины выключены |
| `mcp.roots` | Папки, которые агент объявляет MCP-серверам как разрешённые (roots/list); пусто = корень проекта |
| `lint.enabled` / `lint.rules` | Автолинт и правила (`{file}` — путь к файлу) |
| `tools.shell_timeout` | Таймаут shell-команд, сек |
| `tools.output.*` | Бюджет вывода: `enabled`, `max_chars`, `head_lines`, `tail_lines`, `keep_files`, `no_digest` |
| `tools.search.*` | Поиск по коду: `max_results`, `context`, `max_files` |
| `tools.web.*` | Веб-поиск: `enabled`, `timeout`, `max_chars`, `results`, `excerpt_paragraphs` |
| `snapshots.max_backups` | Сколько последних снапшотов хранить |
| `vscode.*` | Мост к редактору — см. [`integrations.md`](integrations.md) |

В строках JSON работают подстановки: `${env:VAR}`, `${agent_home}`
(`${agent_dir}`), `${project_root}`. Абсолютные пути пишите через прямые слэши
(`D:/work/site`).

## Профили (роли)

Профиль — это набор навыков, который подключается модели. Выбор: `agent.profile`
в конфиге, флаг `--profile <имя>`, команда `:profile <имя>`, список —
`:profiles` или `--list-profiles`. Пусто/`auto` — навыки подбираются по стеку
проекта (`applies_to` в `SKILL.md`).

| Профиль | Навыки |
|---|---|
| `php` | `code-quality`, `php-conventions`, `php-web` |
| `python` | `code-quality`, `python-conventions` |
| `frontend` | `code-quality`, `web-frontend` |
| `java` | `code-quality`, `java-conventions` |
| `kotlin` | `code-quality`, `kotlin-conventions`, `android` |
| `swift` | `code-quality`, `swift-conventions`, `ios` |
| `csharp` | `code-quality`, `csharp-conventions`, `dotnet` |
| `go` | `code-quality`, `go-conventions` |
| `rust` | `code-quality`, `rust-conventions` |
| `ruby` | `code-quality`, `ruby-conventions` |
| `cpp` | `code-quality`, `cpp-conventions` |
| `devops` | `code-quality`, `devops` |

Свой профиль добавляется в секцию `profiles` файла `agent.config.json` — код
агента менять не нужно:

```json
{
  "profiles": {
    "elixir": {
      "description": "Elixir/Phoenix-разработчик",
      "skills": ["code-quality", "elixir-conventions"]
    }
  }
}
```

## DeepSeek API

Агент работает через `chat/completions` и использует то, что описано в
[документации API](https://api-docs.deepseek.com/api/create-chat-completion/):
инструменты (`tools`, `tool_choice="auto"`), режим рассуждений (`thinking` +
`reasoning_effort`), лимит ответа (`max_tokens`), `top_p`, стриминг (`stream`),
отдачу `reasoning_content` в контекст, статистику `prompt_cache_hit_tokens` /
`prompt_cache_miss_tokens` и мультимодальный ввод (vision).

### Thinking mode

| Ключ | Смысл |
|---|---|
| `thinking` | `true` / `false` — включён ли режим рассуждений |
| `reasoning_effort` | `low` / `high` / `max`; `none` выключает рассуждения (алиасы API `minimal`, `medium`, `xhigh`, `ultra` понимаются) |
| `max_tokens` | Лимит ответа; `0` — значение API по умолчанию (8K без thinking, 64K с thinking, 128K при `max`) |
| `top_p` | `0` — не передавать; у `deepseek-flash` действует только в thinking mode (0.95–1.0) |
| `stream` | `false` — ждать ответ целиком (спиннер + markdown); `true` — печатать по мере генерации |

Стриминг по умолчанию выключен. При `:stream on` ответ запрашивается с
`stream=true` и `stream_options={"include_usage": true}`: рассуждения и текст
печатаются по мере генерации, `tool_calls` склеиваются из чанков по `index`, а
`usage` приходит в финальном чанке — статистика и полоса контекста работают так
же, как без стриминга.

По умолчанию рассуждения включены (`high`): модель печатает цепочку мыслей
(`reasoning_content`, в консоли — строкой `💭`), затем ответ. В thinking mode
`temperature` не действует, а `tool_choice` `required`/именованный инструмент API
запрещает — агент использует `auto`.

Переключение на лету: `:think` (текущий режим), `:think off`, `:think max`,
`:think auto` (вернуться к значениям из конфига).

Если ответ обрезан по лимиту токенов (`finish_reason=length`), агент пишет об этом
подсказку — обычно помогает увеличить `api.max_tokens`. Потраченные на
рассуждения токены видны в `:tokens` (`completion_tokens_details.reasoning_tokens`).

### Изображения (vision)

Инструмент `read_image` отправляет картинку модели: скриншоты интерфейса, макеты,
диаграммы, фото ошибок. Формат определяется по содержимому файла (JPEG, PNG, GIF,
WebP), данные уходят inline как `data:` URL, а картинка кладётся в отдельное
`user`-сообщение — в системных и ассистентских сообщениях API изображения
отклоняет.

Секция `vision`: `enabled` (показывать ли инструмент модели), `max_bytes` (лимит
файла, по умолчанию 8 МиБ при ограничении API в 32 МиБ inline), `detail`
(`low` — уменьшение до 512×512, быстрее и дешевле; `high`/`original`/`auto` —
оригинал). `read_file` на картинке не выдаёт мусор: он подсказывает модели вызвать
`read_image`.

## Экономия контекста

Инструменты считают локально, а модели отдают выжимку. Любой результат больше
бюджета (`tools.output.max_chars`, по умолчанию 6000 символов) превращается в
сжатый вид: ошибки (`ERROR`, `FAILED`, `Traceback`), первые и последние строки,
пометки «сколько строк пропущено». Полный вывод сохраняется в
`.agent-cache/output/<инструмент>-<время>.txt` и читается точечно (`read_range`
или `search_code` по этому файлу). Поэтому `pytest`, сборка, `git log` и большие
веб-страницы не «съедают» контекст; `fetch_url(url, query=…)` возвращает абзацы по
теме запроса, а не начало страницы.

Исключения — инструменты чтения (`read_file`, `read_range`, MCP-аналоги): они
ограничены своими лимитами, поэтому `tools.output.no_digest` по умолчанию их не
сжимает.

## Автолинт

После `write_file`/`edit_file` агент сам проверяет синтаксис по правилам секции
`lint` (`php -l`, `node --check`, `python -m py_compile`, `javac`, `kotlinc`,
`swiftc`) и добавляет результат к ответу. Утилита не найдена или правила нет — шаг
пропускается. Отключить: `"lint": { "enabled": false }`.

Правила для Python выполняются **интерпретатором самого агента**
(`sys.executable`), поэтому работают и на macOS/Linux, где команды `python` нет, и
на Windows с `py`-launcher-ом. Байткод линта складывается во временный каталог
системы (`PYTHONPYCACHEPREFIX`), а не в `__pycache__` проекта — автолинт не
мусорит в чужом репозитории.

## Кэш `.agent-cache`

Внутри проекта лежат снапшоты (`backups/`), логи (`logs/`), история
(`history.txt`) и полные выводы инструментов (`output/`). В git не попадает;
чистится через `:cache clear` или `--clear-cache`.
