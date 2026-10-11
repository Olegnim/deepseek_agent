---
name: java-conventions
description: Правила для Java-кода (JVM)
applies_to: [java, jvm, spring, springboot, maven, gradle, quarkus, micronaut]
---

# Java: соглашения

- Именование: `PascalCase` — классы/интерфейсы/enum, `camelCase` — методы и
  поля, `UPPER_SNAKE_CASE` — константы (`static final`), пакеты — строчными
  буквами (`com.example.app`).
- Один публичный класс на файл, имя файла = имя класса.
- Поля — `private final`, где возможно; не открывай изменяемое состояние наружу.
- Сравнение строк и объектов — `equals()` / `Objects.equals()`, не `==`.
- Коллекции и API объявляй по интерфейсам (`List`, `Map`), реализация — деталь.
- Исключения: не глуши (`catch (Exception e) {}`), не лови `Throwable` без нужды;
  для `Closeable` используй try-with-resources.
- Не оставляй `System.out.println` для отладки — используй SLF4J или `java.util.logging`.
- Java 17+: `record`, `sealed`, switch-выражения, `var` для локальных переменных;
  для «возможно пусто» — `Optional`, а не `null`.
- Параллелизм: предпочитай `java.util.concurrent`, не создавай потоки вручную.
- Сборка: Maven (`mvn -q test`) или Gradle (`./gradlew test`); не редактируй
  сгенерированные файлы (target/, build/).
- Секреты и токены — из переменных окружения/конфига, не в коде.
