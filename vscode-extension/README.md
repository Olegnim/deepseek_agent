# DeepSeek Agent Bridge (расширение VS Code)

Мост между CLI-агентом DeepSeek и VS Code. Благодаря нему работу агента
**видно прямо в редакторе**: файлы, с которыми он работает, открываются в
отдельных вкладках, закрываются, показываются в проводнике, а правки можно
смотреть диффом.

```
агент (Python, tools/vscode.py)  --HTTP 127.0.0.1-->  расширение  -->  VS Code
        читает .agent-cache/vscode-bridge.json
```

Работает на **Windows, Linux (Debian/Ubuntu) и macOS**. Не требует ни одной
внешней зависимости: на стороне агента — только стандартная библиотека Python,
на стороне редактора — только Node.js, встроенный в VS Code.

---

## Что умеет

| Команда | Что делает |
|---|---|
| `open`     | открыть файл в новой вкладке и поставить курсор на строку |
| `close`    | закрыть вкладку файла (или последнюю вкладку, открытую агентом) |
| `closeAll` | закрыть все вкладки, открытые агентом |
| `reveal`   | показать файл в проводнике (Explorer) |
| `diff`     | открыть дифф «старая версия ↔ текущая» (снапшот агента) |
| `highlight`| подсветить диапазон строк |
| `ping`     | проверка связи |

Агенту доступны инструменты `vscode_open`, `vscode_close`, `vscode_close_all`,
`vscode_reveal`, `vscode_diff`, `vscode_status`.

---

## Как работает

1. Расширение при старте поднимает HTTP-сервер на `127.0.0.1` (порт выбирается
   автоматически) и пишет в `<workspace>/.agent-cache/vscode-bridge.json` порт,
   токен и pid.
2. Агент (`tools/vscode.py`) читает этот файл и отправляет команды.
3. Сервер слушает только localhost и проверяет токен, поэтому наружу не торчит.
4. При закрытии VS Code файл-дескриптор удаляется. Если VS Code упал и файл
   остался — агент проверяет мост коротким `ping` и считает его недоступным,
   а не зависает и не падает.

### Агент запускается без VS Code — всё в порядке

Интеграция полностью **необязательная** и «fail-safe»:

* нет `.agent-cache/vscode-bridge.json` → инструменты `vscode_*` не попадают в
  список инструментов модели (не тратят контекст) и не упоминаются в промпте;
* авто-открытие правок после `write_file` / `edit_file` молча пропускается;
* битый/пустой дескриптор, мусорный порт, «мёртвый» мост — всё это
  обрабатывается и приводит к тому же результату: агент просто работает как
  обычно;
* выключить интеграцию принудительно: `"vscode": { "enabled": false }`
  в `agent.config.json`.

Ни один сценарий без VS Code не приводит к исключению или зависанию — это
проверяется скриптом `robustness_check.py` (см. ниже).

---

## Установка

Расширение локальное (в Marketplace не публикуется). Варианты:

### Вариант A. «Установить из VSIX» (проще всего)

```powershell
# Windows (PowerShell)
cd vscode-extension
npx --yes @vscode/vsce package      # создаст deepseek-agent-bridge-0.1.0.vsix
code --install-extension deepseek-agent-bridge-0.1.0.vsix
```

```bash
# Linux / macOS
cd vscode-extension
npx --yes @vscode/vsce package
code --install-extension deepseek-agent-bridge-0.1.0.vsix
```

Перезапустите VS Code.

### Вариант B. Папка расширений вручную (без сборки и без Node.js)

Скопируйте папку `vscode-extension` в каталог расширений VS Code под именем
`deepseek-agent-bridge`:

| ОС | Путь |
|---|---|
| Windows | `%USERPROFILE%\.vscode\extensions\deepseek-agent-bridge` |
| Linux | `~/.vscode/extensions/deepseek-agent-bridge` |
| macOS | `~/.vscode/extensions/deepseek-agent-bridge` |

**Windows** — вместо копирования удобно сделать junction, тогда правки
расширения подхватываются без переустановки:

```powershell
New-Item -ItemType Junction -Path "$env:USERPROFILE\.vscode\extensions\deepseek-agent-bridge" -Target "D:\Dev\deepseek_agent\vscode-extension"
```

**Linux / macOS** — симлинк:

```bash
ln -s "$PWD/vscode-extension" ~/.vscode/extensions/deepseek-agent-bridge
```

Затем перезапустите VS Code.

> В VS Code Insiders каталог называется `~/.vscode-insiders/extensions`
> (Windows: `%USERPROFILE%\.vscode-insiders\extensions`).

### Вариант C. Отладка из исходников (F5)

Откройте папку `vscode-extension` в VS Code и нажмите **F5** — откроется окно
«Extension Development Host», где расширение уже активно.

---

## Проверка

1. Откройте проект в VS Code (там, где запускается агент) — появится индикатор
   `$(radio-tower) DeepSeek: мост` в статус-баре.
2. В терминале VS Code запустите агента и введите `:vscode`:

```
✓ мост активен: 127.0.0.1:51823
    проект:  D:\Dev\deepseek_agent
авто-открытие правок: вкл
```

3. Попросите агента что-нибудь сделать — правленые файлы будут открываться в
   новых вкладках.

### Автотесты моста (без VS Code)

Обе проверки запускаются из **корня проекта** и завершаются сами:

```bash
# 1. Протокол: поднимает тестовый HTTP-мост на Node и дёргает Python-инструменты
node vscode-extension/selftest.js

# 2. Устойчивость: агент без VS Code, битый дескриптор, мёртвый мост
python vscode-extension/robustness_check.py     # на Linux/macOS: python3
```

`selftest.js` печатает список отправленных команд, `robustness_check.py` —
24 проверки (все должны быть `PASS`). Оба возвращают код `1` при ошибке.

---

## Команды расширения (Ctrl+Shift+P)

* `DeepSeek Agent: статус моста`
* `DeepSeek Agent: закрыть вкладки агента`
* `DeepSeek Agent: перезапустить мост`

## Настройки расширения

| Настройка | По умолчанию | Описание |
|---|---|---|
| `deepseekAgent.port` | `0` | Порт моста. `0` — выбрать свободный автоматически. |
| `deepseekAgent.host` | `127.0.0.1` | Адрес прослушивания. |

Сторона агента настраивается секцией `vscode` в `agent.config.json`:

| Ключ | По умолчанию | Описание |
|---|---|---|
| `enabled` | `true` | Выключить — инструменты `vscode_*` не показываются модели. |
| `auto_open` | `true` | Открывать файл после `write_file` / `edit_file`. |
| `auto_close_previous` | `false` | Перед открытием нового закрывать предыдущую вкладку агента. |
| `timeout` | `5` | Таймаут HTTP-запроса к мосту, секунды. |

---

## Кроссплатформенные детали

* **Транспорт.** `http://127.0.0.1:<port>` (stdlib `urllib` в Python и `http`
  в Node) — никаких shell-команд, путей через `bash`/`cmd` и внешних утилит.
* **Прокси.** Агент обращается к мосту через `ProxyHandler({})`, поэтому
  корпоративный HTTP-прокси не перехватывает локальные запросы.
* **Пути.** Агент передаёт абсолютные пути; расширение нормализует их через
  `path.normalize`. Windows и macOS сравнивают пути без учёта регистра,
  Linux — с учётом.
* **Песочница.** Открыть/закрыть можно только файлы внутри `PROJECT_ROOT` —
  та же проверка, что и у остальных инструментов агента.
* **Кодировка.** Обмен — UTF-8, поэтому кириллица в путях и заголовках диффов
  не ломается ни на cp1251-консоли Windows, ни на UTF-8 в Linux/macOS.
* **Порт.** По умолчанию выбирается свободный (в т.ч. выше 32768 — на всех трёх
  ОС это безопасно). Если хотите фиксированный — задайте `deepseekAgent.port`.
