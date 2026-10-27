"""诊断目标环境识别 + 工具隔离。

对应 verify_target_environment.py 的 smoke 断言, 这里升级为 pytest 参数化:
  1. 13 条原有回归用例原样保留(行为不能回退);
  2. 补充否定/对照/英文/无动作等边界;
  3. 补充工具隔离的"任何目标都不该放行"不变量。

背景: Docker API 内看到的 CPU/内存是容器的, 不是 Windows 宿主机。
识别错目标 → Agent 拿容器指标冒充宿主机指标 → 报告结论整体失真。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.runtime.target_environment import (
    BYPASS_TOOLS,
    DOCKER_TOOLS,
    LOCAL_SYSTEM_TOOLS,
    UNVERIFIED_TOOLS,
    WINDOWS_TOOLS,
    detect_target_environment,
    filter_tools_by_target,
)

DETECT_CASES = [
    # --- 原有 13 条 ---
    (
        "请诊断我当前 Windows 宿主机的内存使用情况。必须使用实际可用的 Windows "
        "主机监控工具获取数据，区分 Windows 宿主机与 Docker 容器。",
        "windows_host",
    ),
    ("诊断 Windows 宿主机的内存，Docker 容器只用来作对照", "windows_host"),
    ("检查 Docker 容器内存，不要使用 Windows 宿主机的数据", "docker_container"),
    ("诊断我电脑上的 Docker 容器内存", "docker_container"),
    ("不要检查 Windows 宿主机，改为诊断 Docker 容器", "docker_container"),
    ("分析 Windows 11 的内存使用情况", "windows_host"),
    ("排查我的笔记本内存异常", "windows_host"),
    ("查询 docker_stats 对应的 Docker 容器资源", "docker_container"),
    ("比较 Windows 宿主机和 Docker 容器的内存使用率", "unspecified"),
    ("同时诊断 Windows 宿主机和 Docker 容器内存", "unspecified"),
    ("诊断 Windows 宿主机和 Docker 容器的资源差异", "unspecified"),
    ("检查 PostgreSQL 连接池", "unspecified"),
    ("", "unspecified"),
    # --- 补充边界: 否定句不能变成采集目标 ---
    ("只检查 Docker 容器，不要诊断 Windows 宿主机", "docker_container"),
    ("不要诊断 Windows 宿主机和 Docker 容器", "unspecified"),
    # --- 补充边界: 对照/排除语义 ---
    ("诊断 Docker 容器而不是 Windows 宿主机", "docker_container"),
    ("检查 Docker 容器内存，Windows 宿主机数据仅作对照", "docker_container"),
    # --- 补充边界: 无诊断动作时退化为保守规则 ---
    ("帮我看看 Windows 的内存", "windows_host"),
    ("诊断宿主机内存", "unspecified"),
    # --- 补充边界: 英文输入 ---
    ("diagnose windows host memory usage", "windows_host"),
    ("check docker container memory usage", "docker_container"),
]


@pytest.mark.parametrize("query,expected", DETECT_CASES)
def test_detect_target_environment(query: str, expected: str) -> None:
    assert detect_target_environment(query) == expected, f"query={query!r}"


def _tool_names(*names: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(name=name) for name in names]


ALL_TOOL_NAMES = (
    "get_windows_host_metrics",
    "get_local_cpu_memory",
    "list_top_processes",
    "docker_stats",
    "docker_ps",
    "query_windows_event",
    "delegate_to_evidence_collector",
    "search_knowledge_base",
)


@pytest.mark.parametrize(
    "target,expected",
    [
        # 宿主机目标: 只留 Windows 采集工具 + 与采集无关的知识检索
        ("windows_host", {"get_windows_host_metrics", "search_knowledge_base"}),
        # 容器目标: 只留 Docker 只读工具
        ("docker_container", {"docker_ps", "docker_stats", "search_knowledge_base"}),
        # 目标不明: 只留与宿主环境无关的工具
        ("unspecified", {"search_knowledge_base"}),
    ],
)
def test_filter_tools_by_target(target: str, expected: set[str]) -> None:
    tools = _tool_names(*ALL_TOOL_NAMES)
    actual = {tool.name for tool in filter_tools_by_target(tools, target)}  # type: ignore[arg-type]
    assert actual == expected


@pytest.mark.parametrize("target", ["windows_host", "docker_container", "unspecified"])
def test_unsafe_tools_never_survive_any_target(target: str) -> None:
    """不变量: 容器内本机指标 / 未验证工具 / 可绕过过滤的 delegate 永远不可用。

    这三类工具一旦漏进来, 就等于绕过了整套环境隔离, 所以对每个 target 都要断言。
    """
    tools = _tool_names(*ALL_TOOL_NAMES)
    survivors = {tool.name for tool in filter_tools_by_target(tools, target)}  # type: ignore[arg-type]

    assert survivors.isdisjoint(LOCAL_SYSTEM_TOOLS), "LOCAL_SYSTEM_TOOLS 在容器里读到的是容器指标"
    assert survivors.isdisjoint(UNVERIFIED_TOOLS), "UNVERIFIED_TOOLS 部署位置未确认, 不能作为证据来源"
    assert survivors.isdisjoint(BYPASS_TOOLS), "BYPASS_TOOLS 会绕过主 Executor 的环境过滤"


@pytest.mark.parametrize("target", ["windows_host", "docker_container"])
def test_target_specific_tools_are_mutually_exclusive(target: str) -> None:
    """两类环境的采集工具不能同时出现, 否则证据来源会混在一起。"""
    survivors = {
        tool.name
        for tool in filter_tools_by_target(_tool_names(*ALL_TOOL_NAMES), target)  # type: ignore[arg-type]
    }
    if target == "windows_host":
        assert survivors.isdisjoint(DOCKER_TOOLS)
    else:
        assert survivors.isdisjoint(WINDOWS_TOOLS)
