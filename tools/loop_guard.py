"""Защита от зацикливания при снятом лимите шагов (agent.max_steps = 0).

Идея: жёсткий лимит шагов обрывает задачу «на середине», даже если агент
работает нормально. Поэтому по умолчанию лимит снят, а зацикливание ловится
по существу — по повторяющемуся действию.

LoopGuard запоминает подпись последнего вызова инструмента: имя инструмента +
аргументы + хэш результата. Если такая подпись повторяется repeat_limit раз
подряд, это почти наверняка цикл (например, модель снова и снова повторяет
неудачную правку или один и тот же поиск):

  * первый раз — в диалог добавляется предупреждение, чтобы модель сменила
    подход (и счётчик окна начинается заново);
  * если после предупреждения цикл продолжается — задача останавливается.

Настройки — agent.loop_guard в agent.config.json:

    "loop_guard": { "enabled": true, "repeat_limit": 3 }

`enabled: false` или `repeat_limit: 0` полностью отключают защиту.
"""

from __future__ import annotations

import hashlib
import json

import config

WARN = "warn"
STOP = "stop"

_MAX_ARG_TEXT = 120     # сколько символов аргументов показывать в сообщении


def _short_args(args: dict) -> str:
    """Короткое представление аргументов вызова для сообщений пользователю."""
    try:
        text = json.dumps(args or {}, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(args)
    if len(text) > _MAX_ARG_TEXT:
        text = text[:_MAX_ARG_TEXT] + "..."
    return text


def describe_call(tool_name: str, args: dict) -> str:
    """Текстовое описание вызова: `read_file {"path": "src/a.php"}`."""
    return f"{tool_name} {_short_args(args)}"


class LoopGuard:
    """Счётчик повторов одинаковых вызовов инструментов.

    Использование в цикле задачи:

        guard = LoopGuard()
        state = guard.observe(name, args, result)
        if state == STOP: ...остановить задачу
        elif state == WARN: ...добавить guard.warning(name, args) в диалог
    """

    def __init__(self, settings: dict | None = None):
        cfg = config.loop_guard_settings() if settings is None else settings
        self.enabled = bool(cfg.get("enabled", True))
        self.limit = int(cfg.get("repeat_limit") or 0)
        self.signature: str | None = None
        self.repeat = 0
        self.warned: set[str] = set()

    # ---------- состояние ----------

    @property
    def active(self) -> bool:
        """Работает ли защита (включена и задан ненулевой порог)."""
        return self.enabled and self.limit > 0

    def observe(self, tool_name: str, args: dict, result: str) -> str | None:
        """Регистрирует вызов инструмента.

        Возвращает WARN (пора предупредить модель), STOP (остановить задачу)
        или None, если всё в порядке.
        """
        if not self.active:
            return None

        signature = self._signature(tool_name, args, result)
        if signature == self.signature:
            self.repeat += 1
        else:
            self.signature = signature
            self.repeat = 1

        if self.repeat < self.limit:
            return None

        if signature in self.warned:
            return STOP

        # Первое срабатывание — предупреждаем и начинаем окно заново:
        # у модели появляется шанс сменить подход.
        self.warned.add(signature)
        self.repeat = 0
        return WARN

    @staticmethod
    def _signature(tool_name: str, args: dict, result: str) -> str:
        """Подпись вызова: инструмент + аргументы + хэш результата."""
        try:
            payload = json.dumps(args or {}, ensure_ascii=False,
                                 sort_keys=True, default=str)
        except (TypeError, ValueError):
            payload = str(args)
        digest = hashlib.sha1((result or "").encode("utf-8", "replace")).hexdigest()
        return f"{tool_name}|{payload}|{digest}"

    # ---------- сообщения ----------

    def warning(self, tool_name: str, args: dict) -> str:
        """Текст предупреждения для диалога (role=user)."""
        return (
            f"[loop-guard] Действие {describe_call(tool_name, args)} повторилось "
            f"{self.limit} раза подряд с тем же результатом. Не повторяй этот "
            "вызов: измени аргументы, выбери другой инструмент или заверши "
            "задачу коротким ответом с тем, что уже сделано и что мешает."
        )

    def message(self, tool_name: str, args: dict) -> str:
        """Текст остановки задачи."""
        return (
            f"Защита от зацикливания: вызов {describe_call(tool_name, args)} "
            f"повторяется {self.limit} раза подряд с тем же результатом — "
            "останавливаю задачу. Уточните задачу (что именно поправить) или "
            "отключите защиту: agent.loop_guard.enabled = false в agent.config.json."
        )
