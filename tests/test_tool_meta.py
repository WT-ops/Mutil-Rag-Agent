"""ToolMeta 注册表: fail-closed 默认值 + 输入感知只读判定。

这张表是整个安全层的"事实来源": 权限决策、并行编排、结果截断都读它。
它错一个字段, 上层三处会同时错, 所以单独锁住不变量。
"""

from __future__ import annotations

import pytest

from app.runtime.tool_filter import HIGH_RISK_TOOLS
from app.tools.meta import (
    TOOL_META,
    ToolMeta,
    get_meta,
    is_registered,
    register_tool_meta,
    summarize_registry,
    warn_unregistered_tools,
)


def test_unregistered_tool_falls_back_to_conservative_default() -> None:
    """未登记 = 非只读 + 不可并发, 逼开发者显式声明。"""
    meta = get_meta("definitely_not_a_real_tool")

    assert meta.read_only is False
    assert meta.concurrency_safe is False
    assert meta.destructive is False
    assert is_registered("definitely_not_a_real_tool") is False


def test_registered_readonly_tool_is_concurrency_safe_by_declaration() -> None:
    """只读查询工具应当允许并发, 否则并行取证形同虚设。"""
    for name in ("search_knowledge_base", "prom_query", "docker_stats", "list_top_processes"):
        meta = get_meta(name)
        assert meta.read_only is True, name
        assert meta.concurrency_safe is True, name


def test_destructive_tool_is_declared_high_risk() -> None:
    meta = get_meta("docker_restart")

    assert meta.destructive is True
    assert meta.read_only is False
    assert meta.risk_level == "high"


def test_high_risk_set_is_derived_from_meta() -> None:
    """高危集合不能手写, 必须与 meta 声明一致, 否则黑名单会漂移。"""
    expected = {
        name
        for name, meta in TOOL_META.items()
        if meta.risk_level == "high" or meta.destructive
    }
    assert HIGH_RISK_TOOLS == expected
    assert "docker_restart" in HIGH_RISK_TOOLS


def test_input_aware_read_only_overrides_static_flag() -> None:
    """Bash 这类工具: 只读与否取决于入参。"""
    meta = ToolMeta(read_only=False, is_read_only_for_input=lambda payload: payload.get("cmd") == "ls")

    assert meta.effective_read_only({"cmd": "ls"}) is True
    assert meta.effective_read_only({"cmd": "rm -rf /"}) is False
    # 没传入参时不猜, 回退静态声明
    assert meta.effective_read_only(None) is False


def test_input_aware_read_only_falls_back_when_rule_raises() -> None:
    """规则自身抛错时不能把工具误判成只读(不能 fail-open)。"""

    def _boom(payload: dict) -> bool:
        raise RuntimeError("bad input")

    meta = ToolMeta(read_only=False, is_read_only_for_input=_boom)
    assert meta.effective_read_only({"anything": 1}) is False


def test_register_tool_meta_does_not_override_static_declaration() -> None:
    name = "tmp_static_tool"
    TOOL_META[name] = ToolMeta(read_only=True, concurrency_safe=True)
    try:
        register_tool_meta(name, ToolMeta(read_only=False, risk_level="high"))
        assert get_meta(name).read_only is True, "静态声明不应被运行时补登记悄悄覆盖"

        register_tool_meta(name, ToolMeta(read_only=False, risk_level="high"), override=True)
        assert get_meta(name).read_only is False
        assert get_meta(name).risk_level == "high"
    finally:
        TOOL_META.pop(name, None)


def test_warn_unregistered_tools_returns_only_missing() -> None:
    missing = warn_unregistered_tools(["docker_stats", "ghost_tool"])
    assert missing == ["ghost_tool"]


def test_registry_summary_is_consistent() -> None:
    summary = summarize_registry()

    assert summary["total_registered"] == len(TOOL_META)
    assert sum(len(names) for names in summary["by_risk"].values()) == len(TOOL_META)


def test_concurrency_safe_implies_read_only() -> None:
    """可并发的前提是没有副作用; 有写操作却标成可并发会直接产生竞态。"""
    offenders = [
        name
        for name, meta in TOOL_META.items()
        if meta.concurrency_safe and not meta.read_only
    ]
    assert offenders == [], f"这些工具声明了可并发但不是只读: {offenders}"


@pytest.mark.parametrize("name", ["get_local_system_overview", "get_local_cpu_memory", "get_local_disk_usage"])
def test_local_system_tools_are_readonly(name: str) -> None:
    """本机系统快照只读; 一旦被标成可写, 沙箱就失去意义。"""
    assert get_meta(name).read_only is True
    assert get_meta(name).risk_level == "low"
