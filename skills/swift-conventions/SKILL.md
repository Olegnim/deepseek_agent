---
name: swift-conventions
description: Правила для Swift-кода (платформы Apple)
applies_to: [swift, ios, macos, apple, xcode, spm]
---

# Swift: соглашения

- Именование: `PascalCase` — типы, `camelCase` — свойства/функции/элементы enum;
  API-имена читаемые, на английском.
- Предпочитай `let` вместо `var`; value-типы (`struct`, `enum`) — по умолчанию.
- Optionals: избегай force unwrap (`!`) и `try!`; используй `guard let`/`if let`, `??`.
- Ошибки — через `throws`/`try/catch`; `try?` применяй осознанно, не глотай ошибку молча.
- Общую логику выноси в протоколы и `extension`; расширения группируй по назначению.
- Concurrency: `async/await`, `actor` для изолированного состояния, UI — `@MainActor`;
  проверяй `Task.isCancelled`.
- Не оставляй `print()` для отладки — используй `os.Logger` / OSLog.
- Не мутируй UI вне главного потока.
- Сборка/тесты: Xcode (`xcodebuild test -scheme ...`) или SwiftPM (`swift build`, `swift test`).
- Секреты — в Keychain, xcconfig или окружении, не в коде.
