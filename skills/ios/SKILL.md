---
name: ios
description: Правила разработки приложений под iOS (UIKit/SwiftUI)
applies_to: [ios, swift, apple, xcode, uikit, swiftui, macos]
---

# iOS: приложения

## Архитектура
- Слой представления отделён от логики: `View`/`ViewController` — только UI,
  бизнес-логика — в моделях и сервисах, состояние — в `ObservableObject`
  или `@Observable`.
- Зависимости передавай явно (внедрение); избегай глобальных синглтонов.
- Сетевые и дисковые операции — асинхронно, главный поток не блокируем.

## UI (следуй Apple Human Interface Guidelines)
- SwiftUI: stateless-`View`, состояние — `@State`/`@Binding`/`@StateObject`,
  списки — `List`/`ForEach` со стабильными `id`.
- UIKit: переиспользуй ячейки (`dequeueReusableCell`), не держи тяжёлые объекты
  в ячейке, не пересоздавай представления в цикле.
- Вёрстка — через Auto Layout/constraints (или SwiftUI-модификаторы), без хардкода
  координат под один экран.
- Прорабатывай состояния пусто/загрузка/ошибка; итерации по UI — через SwiftUI Previews.
- Доступность: `accessibilityLabel`, Dynamic Type, контраст, достаточные тач-таргеты.

## Ресурсы и данные
- Локализация — через `Localizable.strings`/String Catalog, не хардкод строк.
- Ресурсы — в каталогах `.xcassets` (светлая/тёмная тема, векторные ассеты).
- Разрешения (`Info.plist` usage descriptions) — только нужные и с понятным текстом.
- Секреты и токены — в Keychain, не в `UserDefaults` и не в коде.

## Проверка
- Тесты — XCTest / Swift Testing, UI — XCUITest.
- Не меняй `Info.plist`, подписи и `project.pbxproj` без прямой задачи.
