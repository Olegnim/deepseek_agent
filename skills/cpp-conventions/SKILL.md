---
name: cpp-conventions
description: Правила для C и C++ (CMake, современный C++)
applies_to: [c, cpp, cplusplus, cmake, clang, gcc]
---

# C / C++: соглашения

- Сборка — `cmake --build build` (или `make`), проверка синтаксиса одного файла —
  `g++ -fsyntax-only -std=c++20 file.cpp` с теми же `-I`/`-D`, что у проекта
  (иначе будут ложные ошибки на `#include`), тесты — `ctest --test-dir build`.
- Стандарт — как в `CMakeLists.txt` (`CMAKE_CXX_STANDARD`); не смешивай
  C- и C++-стиль в одном модуле.
- Ресурсы: `std::unique_ptr`/`std::shared_ptr` и RAII вместо ручных `new/delete`;
  владение в API — явное (`T*` — не владеет, `unique_ptr<T>` — владеет).
- Константность: `const`/`const&` в параметрах, `constexpr` для констант,
  `[[nodiscard]]` для функций, результат которых нельзя терять.
- Опасные операции: `sizeof`/`strcpy`/`sprintf`/ручная арифметика указателей —
  заменяй на `std::array`/`std::span`/`std::string_view`/`fmt`; границы проверяй.
- Заголовки: `#pragma once` (или include guards), минимум `#include` в `.h`,
  вперёд-объявления вместо лишних зависимостей; никаких `using namespace std;` в
  заголовках.
- Ошибки: исключения — по проекту; в C — коды возврата и `goto cleanup` в одном
  месте; `assert` для инвариантов, не для пользовательского ввода.
- Неопределённое поведение: без чтения неинициализированных переменных, без
  выхода за границы, без `reinterpret_cast` без причины; прогоняй тесты с
  санитайзерами (`-fsanitize=address,undefined`), если это принято в проекте.
- Секреты — из окружения/конфигурации, не в коде; логи без `printf` в правках.
