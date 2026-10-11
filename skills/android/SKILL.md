---
name: android
description: Правила разработки приложений под Android (Kotlin/Java)
applies_to: [android, kotlin, java, gradle]
---

# Android: приложения

## Архитектура
- UI отделён от логики: `Activity`/`Fragment`/Compose отвечают за отображение и
  события, работа с данными — в `ViewModel` и репозиториях.
- Состояние экрана держи в `ViewModel` (переживает поворот):
  `StateFlow`/`LiveData`, а не поля во `Fragment`.
- Не держи ссылки на `Activity`/`Context` в синглтонах и долгоживущих объектах —
  это утечки памяти.
- Сеть и БД — вне главного потока (корутины), UI-поток не блокируем.

## Ресурсы и UI
- Строки, размеры, цвета — в `res/values` (`strings.xml`, `dimens.xml`, `colors.xml`),
  не хардкод в коде.
- Compose: stateless-компоненты, состояние поднимаем наверх (state hoisting),
  списки — через `LazyColumn`/`LazyRow` с устойчивым `key`.
- Доступность: `contentDescription` у иконок, достаточный размер тач-таргетов,
  поддержка Dynamic Type / масштаба шрифта.

## Манифест и сборка
- Разрешения — только необходимые; опасные запрашивай в рантайме.
- `applicationId`, `minSdk`, `targetSdk` не меняй без задачи; учитывай поведение
  на новых версиях API.
- Секреты и ключи — не в коде и не в закоммиченном `BuildConfig`; используй
  `local.properties` или секреты CI.
- ProGuard/R8: не ломай правила обфускации, `@Keep` — точечно.

## Проверка
- Модульные тесты — JUnit; инструментальные — Espresso.
- Сборка: `./gradlew assembleDebug`, тесты: `./gradlew test`.
