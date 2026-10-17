"""Тесты мягкого режима планирования.

Состояния: `auto` (по умолчанию) → `planning` (только PLAN.md) → `run`
(план утверждён, автопилот) и `off` (без планирования). Проверяется смена
состояний, запрет правок до утверждения плана и включение автопилота.
"""

from __future__ import annotations

import asyncio

import pytest


def run_tool(agent_module, name: str, args: dict):
    return asyncio.run(agent_module.execute_tool(name, args))


@pytest.fixture
def plan_default(agent_module):
    """Возвращает агента в состояние по умолчанию (auto) до и после теста."""
    agent_module.cmd_plan("auto")
    yield agent_module
    agent_module.cmd_plan("auto")


# ---------- Состояния режима ----------

def test_plan_mode_is_auto_by_default():
    import agent
    assert agent.PLAN_MODE == "auto"


def test_plan_on_switches_to_planning(plan_default):
    assert plan_default.cmd_plan("on") is True
    assert plan_default.PLAN_MODE == "planning"


def test_plan_status_does_not_change_mode(plan_default):
    assert plan_default.cmd_plan() is False
    assert plan_default.PLAN_MODE == "auto"


def test_unknown_plan_argument_keeps_mode(plan_default):
    assert plan_default.cmd_plan("нечто") is False
    assert plan_default.PLAN_MODE == "auto"


def test_plan_off_means_no_planning(plan_default):
    assert plan_default.cmd_plan("off") is True
    assert plan_default.PLAN_MODE == "off"


def test_plan_auto_returns_to_default(plan_default):
    plan_default.cmd_plan("on")
    assert plan_default.cmd_plan("auto") is True
    assert plan_default.PLAN_MODE == "auto"


# ---------- Системный промпт ----------

def test_prompt_always_describes_plan_file(plan_default):
    prompt = plan_default.build_system_prompt()
    assert "PLAN.md" in prompt
    assert ":plan approve" in prompt


def test_prompt_auto_mode_offers_choice(plan_default):
    """В режиме auto агент должен спросить: планировать или выполнить сразу."""
    prompt = plan_default.build_system_prompt()
    assert "АВТО (по умолчанию)" in prompt
    assert "Планировать" in prompt


def test_prompt_in_planning_mode_forbids_edits(plan_default):
    plan_default.cmd_plan("on")
    assert "ПЛАНИРОВАНИЕ" in plan_default.build_system_prompt()


def test_prompt_in_autopilot_mode_asks_to_go_through_steps(plan_default):
    plan_default.cmd_plan("on")
    plan_default.cmd_plan("approve")
    prompt = plan_default.build_system_prompt()
    assert "АВТОПИЛОТ" in prompt
    assert "- [x]" in prompt          # прогресс отмечается в PLAN.md


def test_prompt_off_mode_skips_planning(plan_default):
    plan_default.cmd_plan("off")
    assert "Планирование выключено" in plan_default.build_system_prompt()


# ---------- Запрет правок до утверждения ----------

def test_planning_blocks_edit_of_other_files(plan_default):
    plan_default.cmd_plan("on")
    out = run_tool(plan_default, "write_file",
                   {"path": "src/a.py", "content": "x = 1\n"})
    assert out.startswith("ERROR")
    assert "PLAN.md" in out
    assert not (plan_default.PROJECT_ROOT / "src" / "a.py").exists()


def test_planning_allows_writing_plan_file(plan_default):
    plan_default.cmd_plan("on")
    out = run_tool(plan_default, "write_file",
                   {"path": "PLAN.md", "content": "- [ ] T1 — тест\n"})
    assert not out.startswith("ERROR")
    assert (plan_default.PROJECT_ROOT / "PLAN.md").is_file()


def test_auto_mode_does_not_block_edits(plan_default):
    out = run_tool(plan_default, "write_file",
                   {"path": "src/a.py", "content": "x = 1\n"})
    assert not out.startswith("ERROR")


def test_planning_blocks_mcp_edits(plan_default):
    plan_default.cmd_plan("on")
    out = run_tool(plan_default, "filesystem__write_file",
                   {"path": "src/b.py", "content": "y = 2\n"})
    assert out.startswith("ERROR")


def test_plan_guard_allows_plan_file_and_shell(plan_default):
    plan_default.cmd_plan("on")
    assert plan_default.plan_guard("filesystem__write_file",
                                   {"path": "src/b.py"}).startswith("ERROR")
    assert plan_default.plan_guard("filesystem__write_file", {"path": "PLAN.md"}) == ""
    assert plan_default.plan_guard("write_file", {"path": "docs/PLAN.md"}) == ""
    assert plan_default.plan_guard("run_shell", {"command": "pytest -q"}) == ""
    assert plan_default.plan_guard("read_file", {"path": "src/b.py"}) == ""


def test_approve_allows_edits_and_turns_confirmations_off(plan_default):
    plan_default.CONFIRM_MODE = True
    plan_default.cmd_plan("on")
    assert plan_default.cmd_plan("approve") is True
    assert plan_default.PLAN_MODE == "run"
    assert plan_default.CONFIRM_MODE is False

    out = run_tool(plan_default, "write_file",
                   {"path": "src/a.py", "content": "x = 1\n"})
    assert not out.startswith("ERROR")
    assert (plan_default.PROJECT_ROOT / "src" / "a.py").is_file()


def test_plan_off_restores_previous_confirm_mode(plan_default):
    plan_default.CONFIRM_MODE = True
    plan_default.cmd_plan("on")
    plan_default.cmd_plan("approve")
    assert plan_default.cmd_plan("off") is True
    assert plan_default.PLAN_MODE == "off"
    assert plan_default.CONFIRM_MODE is True


def test_plan_off_keeps_confirmations_off_if_they_were_off(plan_default):
    plan_default.CONFIRM_MODE = False
    plan_default.cmd_plan("on")
    plan_default.cmd_plan("approve")
    plan_default.cmd_plan("off")
    assert plan_default.CONFIRM_MODE is False


# ---------- Прогресс плана ----------

def test_plan_progress_counts_checkboxes(plan_default):
    (plan_default.PROJECT_ROOT / "PLAN.md").write_text(
        "# План\n\n- [x] T1\n- [ ] T2\n- [ ] T3\n", encoding="utf-8"
    )
    assert plan_default.plan_progress() == (1, 3)


def test_plan_progress_without_file_is_zero(plan_default):
    assert plan_default.plan_progress() == (0, 0)


# ---------- Роутинг команды ----------

def test_handle_command_routes_plan(plan_default):
    messages: list = []
    assert asyncio.run(plan_default.handle_command(":plan on", messages)) is True
    assert plan_default.PLAN_MODE == "planning"
    assert asyncio.run(plan_default.handle_command(":plan approve", messages)) is True
    assert plan_default.PLAN_MODE == "run"
    assert asyncio.run(plan_default.handle_command(":plan auto", messages)) is True
    assert plan_default.PLAN_MODE == "auto"
