"""Executor 前的工具收窄: 谁能被 LLM 看见, 谁只能进 decisions。

核心约束(来自 tool_filter 的设计):
  - allow + ask 暴露给模型, deny 连看都看不到;
  - Skill 白名单外只放行"只读"工具(避免诊断拿不到真实数据);
  - 写/通知/高危工具必须显式写进 allowed_tools 才可能出现。

这里用假工具对象 + 假 Registry 隔离外部依赖, 不连 Milvus/Redis/MCP。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.runtime.tool_filter as tool_filter
from app.config import settings
from app.runtime.permissions import PermissionMode
from app.runtime.tool_filter import filter_tools_for_skill
from tests._helpers import patched


def _tools(*names: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(name=name) for name in names]


def _registry(allowed: list[str]):
    skill = SimpleNamespace(
        name="host_resource_diagnosis",
        allowed_tools=list(allowed),
        risk_level="low",
    )
    return SimpleNamespace(get_or_generic=lambda _name: skill)


def _run(allowed: list[str], tools, mode=PermissionMode.NORMAL, *, block_high_risk=True):
    """在受控 settings + 假 registry 下调用被测函数。"""
    with patched(
        tool_filter,
        get_skill_registry=lambda: _registry(allowed),
        expose_tools_with_lazy_mcp=lambda visible, names, enabled=False: visible,
    ), patched(
        settings,
        guardrails_block_high_risk_tools=block_high_risk,
        guardrails_allow_notification_tools=False,
        mcp_lazy_tools_enabled=False,
    ):
        return filter_tools_for_skill("host_resource_diagnosis", tools, mode=mode)


def test_empty_allowlist_refuses_to_expose_anything() -> None:
    """Skill 没配 allowed_tools 时宁可什么都不给, 也不退化成"全量放开"。"""
    visible, decisions = _run([], _tools("docker_stats", "search_knowledge_base"))

    assert visible == []
    assert decisions == {}


def test_readonly_tools_are_auto_added_but_write_tools_are_not() -> None:
    tools = _tools("search_knowledge_base", "list_top_processes", "docker_restart")
    visible, decisions = _run(["search_knowledge_base"], tools)

    visible_names = {tool.name for tool in visible}
    assert visible_names == {"search_knowledge_base", "list_top_processes"}
    assert "docker_restart" not in decisions, "白名单外的写工具不应进入候选集"


def test_high_risk_tool_in_allowlist_is_denied_and_hidden() -> None:
    tools = _tools("docker_restart", "search_knowledge_base")
    visible, decisions = _run(["docker_restart", "search_knowledge_base"], tools)

    assert decisions["docker_restart"].behavior == "deny"
    assert decisions["docker_restart"].reason_type == "guardrail_high"
    assert "docker_restart" not in {tool.name for tool in visible}, "deny 的工具不能暴露给模型"


def test_high_risk_tool_visible_when_guardrail_disabled() -> None:
    tools = _tools("docker_restart")
    visible, decisions = _run(["docker_restart"], tools, block_high_risk=False)

    assert decisions["docker_restart"].behavior == "allow"
    assert {tool.name for tool in visible} == {"docker_restart"}


def test_read_only_mode_hides_write_tool_but_keeps_readonly() -> None:
    tools = _tools("docker_restart", "docker_stats")
    visible, decisions = _run(
        ["docker_restart", "docker_stats"],
        tools,
        mode=PermissionMode.READ_ONLY,
        block_high_risk=False,
    )

    assert decisions["docker_restart"].behavior == "deny"
    assert decisions["docker_restart"].reason_type == "mode_read_only"
    assert {tool.name for tool in visible} == {"docker_stats"}


def test_ask_destructive_exposes_tool_with_ask_decision() -> None:
    """ask 的工具要暴露给模型(否则模型学不会"先申请"), 但运行时必须走审批。"""
    tools = _tools("docker_restart")
    visible, decisions = _run(
        ["docker_restart"],
        tools,
        mode=PermissionMode.ASK_DESTRUCTIVE,
        block_high_risk=True,
    )

    assert decisions["docker_restart"].behavior == "ask"
    assert {tool.name for tool in visible} == {"docker_restart"}


def test_denied_tools_are_never_visible_regardless_of_mode() -> None:
    """不变量: decisions 里所有 deny 的项, 都不能出现在 visible 里。"""
    tools = _tools("docker_restart", "list_top_processes", "query_windows_event", "search_knowledge_base")
    allowed = ["docker_restart", "search_knowledge_base"]

    for mode in (PermissionMode.NORMAL, PermissionMode.READ_ONLY, PermissionMode.ASK_DESTRUCTIVE):
        visible, decisions = _run(allowed, tools, mode=mode)
        denied = {name for name, decision in decisions.items() if decision.behavior == "deny"}
        assert denied.isdisjoint({tool.name for tool in visible})


def test_duplicate_tools_are_deduplicated() -> None:
    """同一工具被重复注册时只暴露一次, 否则模型会看到重复 schema。"""
    tools = _tools("docker_stats", "docker_stats", "search_knowledge_base")
    visible, _ = _run(["search_knowledge_base"], tools)

    names = [tool.name for tool in visible]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("mode", list(PermissionMode))
def test_every_mode_returns_decisions_for_every_visible_tool(mode: PermissionMode) -> None:
    """visible 与 decisions 必须对齐, 否则 tool_runner 会在运行时拿到 KeyError。"""
    tools = _tools("docker_stats", "search_knowledge_base")
    visible, decisions = _run(["docker_stats", "search_knowledge_base"], tools, mode=mode)

    assert {tool.name for tool in visible} <= set(decisions)
