---
name: android
description: Правила разработки приложений под Android (Kotlin/Java)
applies_to: [android, kotlin, java, gradle]
---

# Android: приложения

Рекомендации опираются на официальное руководство Google «Guide to app
architecture» и «Recommendations for Android architecture».

## Архитектура
- Слои: UI (`Activity`/`Fragment`/Compose + `ViewModel`) → (опц. Domain) → Data
  (репозитории). Поток данных однонаправленный (UDF): события вверх,
  состояние вниз.
- UI отделён от логики: `Activity`/`Fragment`/Compose отвечают за отображение и
  события, работа с данными — в `ViewModel` и репозиториях.
- `ViewModel` отдаёт неизменяемое состояние (`StateFlow<UiState>`), во View —
  `collectAsStateWithLifecycle`; для горячих потоков — `stateIn(..., WhileSubscribed(5_000))`.
- Единственный источник истины: состояние — во `ViewModel`, данные — в репозитории
  (сеть/БД за ним), UI не ходит в сеть напрямую.
- Не держи ссылки на `Activity`/`Context` в синглтонах и долгоживущих объектах —
  это утечки памяти.
- Внедрение зависимостей — через Hilt/Koin, а не вручную в конструкторах UI.
- Сеть и БД — вне главного потока (корутины), UI-поток не блокируем.
- Именование: `XxxViewModel`, `XxxRepository`, `XxxUiState`, `XxxScreen`.

## Ресурсы и UI
- Строки, размеры, цвета — в `res/values` (`strings.xml`, `dimens.xml`, `colors.xml`),
  не хардкод в коде.
- Compose: stateless-компоненты, состояние поднимаем наверх (state hoisting),
  списки — через `LazyColumn`/`LazyRow` с устойчивым `key`.
- Доступность: `contentDescription` у иконок, достаточный размер тач-таргетов,
  поддержка масштаба шрифта.

## Манифест и сборка
- Разрешения — только необходимые; опасные запрашивай в рантайме.
- `applicationId`, `minSdk`, `targetSdk` не меняй без задачи; учитывай поведение
  на новых версиях API.
- Секреты и ключи — не в коде и не в закоммиченном `BuildConfig`; используй
  `local.properties` или секреты CI.
- ProGuard/R8: не ломай правила обфускации, `@Keep` — точечно.

## Проверка
- Тестируй `ViewModel` и репозитории юнит-тестами (без Android-фреймворка);
  UI — Espresso/instrumented.
- Сборка: `./gradlew assembleDebug`, тесты: `./gradlew test`.
